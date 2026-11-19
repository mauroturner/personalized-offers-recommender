"""The launch: the choice, the first round's models and lists, the seal and the registry (RF12, RF13, AC14, AC16, AC36; M04; risk item 1; decisions D11, D12, D21, D23; plan sections 11 and 13).

``run_launch`` is what ``fit_recipe`` does in the launch run. The launch delivery is loaded; the test has not started. In this order, and each step leaves what the next one needs:

1. the lines are read from the warehouse and refused (``ValidationLeakError``, M04, runbook R5) if one is dated on or after the first day of the test: nothing of the test can be in the choice;
2. the base of the first round (the launch cohort) and the draw of the control group are computed (a pure function of the sealed seed and of the history: the same each time);
3. without a seal the recipe is **chosen** in the validation rounds (``choose.choose``); with a seal of the same configuration it is **adopted** from it, with no choice (the registry of the models failed
   after the seal, and the next ``fit_recipe`` goes on from what was sealed); with a seal of another configuration everything is post-seal (M03) and nothing is sealed;
4. the first round's models are fitted on the history of the launch (the popularity of the round and the model of the chosen recipe), the lists of its customers are built and fingerprinted, and the
   artifacts are written under ``<models>/.candidates-<run_key>/``, which is **kept if anything after this fails**;
5. the **seal is written before anything is registered** (``write_launch_seal``: created exclusively, never rewritten); an adopted launch compares what it recomputed (the draw, the lists) with the
   seal and refuses with a ``SealMismatchError`` that names what differs (runbook R7), writing nothing;
6. the base of the round and its assignments are stored (idempotent) and the artifacts are moved to ``<models>/<round>/<component>/`` and registered in ``model_registry`` in one transaction, so a
   failure leaves no registry row without its artifact.

A launch that finds the seal and the registry complete is ``done``: it writes nothing and checks that what is stored is what was sealed.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import datetime, time as clock
from pathlib import Path
from typing import Any

import numpy as np

from personaloffers import base, choose, holdout, offers, registry, warehouse
from personaloffers import calendar as cal
from personaloffers.files import move_folder
from personaloffers.recommend import artifacts, blend, context
from personaloffers.recommend.blend import Recipe

POPULARITY = "popularity"


@dataclass(frozen=True)
class LaunchResult:
    mode: str                  # fresh, adopt or done
    seal_state: str            # what the seal was to this configuration before the launch: none, match or post_seal
    round_id: str
    recipe: Recipe
    choice: choose.Choice
    config_sha256: str
    holdout_fingerprint: str
    lists_fingerprint: str
    sealed: bool               # this launch wrote the launch part of the seal
    registered: bool           # this launch registered the round's models
    seconds: dict[str, float]


def candidates_folder(models_dir: Path, run_key: str) -> Path:
    return Path(models_dir) / f".candidates-{run_key}"


def _launch_part(view: Any, run_key: str, monday: Any, choice: choose.Choice, assignment: Any, cov: Any, lists: offers.RoundLists, codes: np.ndarray) -> dict[str, Any]:
    balance = holdout.balance(cov, assignment)
    return {
        "config_sha256": registry.config_fingerprint(view), "config": registry.view_to_dict(view), "run_key": run_key, "as_of": datetime.combine(monday, clock.min).isoformat(),
        "validation": choose.to_dict(choice),
        "recipe": _recipe_dict(choice.chosen.recipe), "baselines": {key: _recipe_dict(c.recipe) for key, c in sorted(choice.baselines.items())},
        "holdout": {"fingerprint": holdout.fingerprint(assignment), "sizes": holdout.sizes(assignment), "balance": balance, "max_abs_smd": max(abs(v) for v in balance.values())},
        "lists": {"round_id": cal.round_id(monday), "customers": len(lists.customers), "rows": int(lists.products.size), "fingerprint": offers.lists_fingerprint(lists, codes)},
    }


def _recipe_dict(recipe: Recipe) -> dict[str, Any]:
    return {"model": recipe.model, "size": recipe.size, "regularization": recipe.regularization, "weight": recipe.weight, "name": recipe.name}


def round_components(data: Any, recipe: Recipe, model: Any, view: Any) -> dict[str, tuple[dict[str, np.ndarray], dict[str, Any]]]:
    """The two components of the round: its popularity (the counts and the orders every list needs) and the chosen model, each with its arrays and its parameters."""
    popularity_arrays = {"codes": data.codes, "popularity": data.popularity, "recent": data.recent, "trend": data.trend, "tie_rank": data.tie_rank, "fallback": data.fallback}
    popularity_params = {"fallback_days": view.recommend.fallback_days, "trend_days": view.grid.blend_trend_days, "products": int(len(data.codes)), "customers": int(len(data.customers))}
    model_params = {"model": recipe.model, "size": recipe.size, "regularization": recipe.regularization, "weight": recipe.weight, "name": recipe.name}
    return {POPULARITY: (popularity_arrays, popularity_params), recipe.model: (blend.model_arrays(recipe, model), model_params)}


def _install(candidate: artifacts.Artifact, target: Path) -> None:
    """Move a candidate artifact to its final place; one that is there already must be the same artifact (a previous attempt moved it) and then the candidate is dropped."""
    if target.exists():
        if artifacts.artifact_sha256(target) != candidate.sha256:
            raise artifacts.ArtifactError(f"{target.parent.name}/{target.name} ya está en su lugar con otro contenido que el candidato: lo registrado no se reemplaza (runbook R6)")
        shutil.rmtree(candidate.path)
    else:
        move_folder(candidate.path, target)


def _stored_matches_seal(conn: Any, models_dir: Path, round_id: str, sealed: dict[str, Any], assignment: Any) -> None:
    """A finished launch is checked against the seal: the draw that is recomputed and the one that is stored are the sealed one, and every registered artifact is on disk with its registered hash."""
    stored = holdout.read_assignments(conn)
    registry.check_launch(sealed, {"holdout_fingerprint": holdout.fingerprint(assignment)})
    registry.check_launch(sealed, {"holdout_fingerprint": holdout.fingerprint(stored[stored["assigned_round"] == round_id]) if len(stored) else ""})
    for component, (path, digest, _params) in warehouse.registered_models(conn, round_id).items():
        try:
            artifacts.verify_component(Path(models_dir) / path, digest)
        except artifacts.ArtifactError as error:
            raise artifacts.ArtifactError(f"el artefacto {component} de la ronda {round_id} no es el que se registró: {error} (runbook R6)") from error


def run_launch(conn: Any, view: Any, run_key: str, *, models_dir: Path, seal_path: Path) -> LaunchResult:
    """Run the launch (see the module). `view` is the sealed view, `run_key` the run that loaded the launch delivery."""
    started = time.perf_counter()
    seconds: dict[str, float] = {}
    fingerprint = registry.config_fingerprint(view)
    state = registry.seal_state(seal_path, fingerprint)
    monday = view.calendar.test_first_round
    round_id = cal.round_id(monday)
    lines = warehouse.read_lines(conn)
    if not len(lines):
        raise ValueError("el almacén no tiene líneas: la entrega del lanzamiento no está cargada")
    choose.check_validation_lines(lines, view)
    history = base.history_before(lines, monday)
    cov = base.base_table(history, monday, view)
    assignment = holdout.assign_cohort(cov, view)
    registered = warehouse.registered_models(conn, round_id)
    sealed = registry.read_seal(seal_path)["launch"] if state == "match" else None

    if sealed is not None and registered:
        _stored_matches_seal(conn, models_dir, round_id, sealed, assignment)
        choice = choose.from_dict(sealed["validation"])
        return LaunchResult("done", state, round_id, choice.chosen.recipe, choice, fingerprint, sealed["holdout"]["fingerprint"], sealed["lists"]["fingerprint"], False, False,
                            {"total": round(time.perf_counter() - started, 3)})
    if registered:
        raise registry.SealMismatchError(f"la ronda {round_id} ya tiene sus modelos registrados y no hay un sello de esta configuración ({state}): un análisis nuevo se hace en una carpeta nueva (runbook R12)")
    if sealed is not None:
        mode, choice = "adopt", choose.from_dict(sealed["validation"])
    else:
        mode, choice = "fresh", choose.choose(lines, view)
    seconds["choice"] = round(time.perf_counter() - started, 3)

    fitted = time.perf_counter()
    data = context.prepare(history, monday, cov["customer_id"].to_numpy(), view)
    recipe = choice.chosen.recipe
    model = blend.fit_model(data, recipe, view)
    lists = offers.round_lists(data, recipe, view, cache={blend.cache_key(recipe): blend.model_scores(data, recipe, model)})
    seconds["fit"] = round(time.perf_counter() - fitted, 3)
    part = _launch_part(view, run_key, monday, choice, assignment, cov, lists, data.codes)
    if mode == "adopt":
        registry.check_launch(sealed, {"validation_digest": choose.digest(choice), "recipe": recipe.name, "holdout_fingerprint": part["holdout"]["fingerprint"],
                                       "lists_fingerprint": part["lists"]["fingerprint"]})

    candidates = candidates_folder(models_dir, run_key)
    components = round_components(data, recipe, model, view)
    written = {component: artifacts.write_component(candidates, round_id, component, arrays, params) for component, (arrays, params) in components.items()}
    sealed_now = False
    if mode == "fresh" and state == "none":
        registry.write_launch_seal(seal_path, part)
        sealed_now = True

    warehouse.store_round_base(conn, round_id, monday, cal.period_of(monday, view), run_key, cov, assignment)
    rows = []
    for component, artifact in written.items():
        _install(artifact, Path(models_dir) / round_id / component)
        rows.append((component, components[component][1], f"{round_id}/{component}", artifact.sha256, len(history), seconds["fit"]))
    warehouse.register_models(conn, round_id, rows)
    shutil.rmtree(candidates, ignore_errors=True)
    seconds["total"] = round(time.perf_counter() - started, 3)
    return LaunchResult(mode, state, round_id, recipe, choice, fingerprint, part["holdout"]["fingerprint"], part["lists"]["fingerprint"], sealed_now, True, seconds)
