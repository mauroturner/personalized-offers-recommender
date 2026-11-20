"""The documentation is checked like code (AC23, AC39; RF26; RNF14; plan, sections 24.2, 25 and 26). Adapted from project 07's ``tests/docs/test_docs.py``.

The README has the headings of plan section 25 in their order, its results block is the sealed summary that ``docs-sync`` copies (never one written by hand), and it says the unfavourable
verdict («No se cumple» for C03) in «El problema», «La solución» and «Los resultados»; the model card has the contents the plan lists and every verdict as the summary writes it; every interval
bound the documents quote is the summary's at the decimals the document writes; no document claims the effect of an offer (D16); no figure of the real run is called synthetic; every decision has
its seven fields; the test count the documents give is the one of the session's collection; every memory figure names its counter; every test the plan names exists; every unit and every log
entry the documents cite is in the log; the dictionary's tables are the ones ``docs_sync`` writes from the semantic model; the runbook has R1 to R12; the step by step cites commits that exist;
the advisories of the native reviews have their status; and the rows of project 08 in the root documents carry the real figures. These tests read the versioned Markdown, the versioned reports
and the plan, and run nothing. Every document is read once per module.
"""

from __future__ import annotations

import ast
import getpass
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from personaloffers.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Una oferta para cada cliente, armada sola"
USER_NAMES = {name.lower() for name in (getpass.getuser(), Path.home().name) if name}   # this machine's user, read here and never written in a test
EMAIL = re.compile(r"\S+@\S+")
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)|/c/(?:Users)|Users\\|/home/\w+/")
TRACKED_PATH = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)|/c/(?:Users)")   # the code and the tests write the patterns that detect a local path, so the tracked files are searched for the paths only
README_HEADINGS = [   # plan, section 25, in this order (AC39)
    "El problema", "La solución", "Los resultados", "En qué consiste", "Los datos", "Los algoritmos", "El producto", "La documentación",
    "Con IA, de punta a punta", "Para qué sirve", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "Los recomendadores", "La elección y la lista", "El control y el experimento", "Criterios y resultados", "Limitaciones", "Tiempos y memoria",
    "La suite rápida",
]
FAILED = ["C03"]   # what the sealed run says (L133)
PASSED = ["C01", "C02", "C04", "C05", "C06", "C07", "C08", "C09"]
RESULTS_HEADING = "## Resumen de la evaluación"   # the first line of the summary, copied as it is
DOCS = ("data-dictionary.md", "runbook.md", "paso-a-paso.md", "review-advisories.md", "evaluation.md")   # evaluation.md joined them with the independent evaluation (plan section 28)
LOG = "odd/tasks/portfolio-projects.md"
FIRST_LOG_ENTRY = 117   # L117 starts project 08
UNITS_DONE = [f"U{n:02d}" for n in range(1, 23)]   # U01 to U22 have their entry in the log (U21 in L133; U22 is named there as the next unit)
STATUSES = ("corregida", "refutada", "dejada con evidencia", "abierta")
DECISION_FIELDS = ("Contexto", "Opciones", "Decisión", "Motivo", "Afecta", "Quién", "Estado")
COUNTERS = ("PeakWorkingSetSize", "PeakPagefileUsage", "conjunto de trabajo", "memoria comprometida")
MEMORY_FIGURE = re.compile(r"\d[\d.]*(?:,\d+)?\s?(?:MB|GB|MiB|GiB)\b")
MEMORY_WORDS = re.compile(r"pico|peak_|conjunto de trabajo|comprometid|memoria", re.IGNORECASE)   # the size of a file, an image or a disk is not a memory figure
SENTENCE_END = re.compile(r"(?<=\.)\s+")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
NAMED_TEST = re.compile(r"(tests/[\w/]+\.py)?::(test_\w+)")
CUSTOMER_NUMBER = re.compile(r"\b1[2-8]\d{3}\b")   # five digits from 12000 to 18999, a range that holds every customer number of the archive: a document names none of them (D30)
SEAL_SHA256 = "fa393815bb5eb6d39a8b29f0167200f0d4f6305da30980b636fee5a9b1c5cc36"


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model_card(project_root: Path) -> str:
    return read(project_root, "model-card.md")


@pytest.fixture(scope="module")
def summary(project_root: Path) -> dict:
    return json.loads((project_root / "reports" / "evaluation_summary.json").read_text(encoding="utf-8"))


_READ: dict[Path, str] = {}


def read(project_root: Path, name: str) -> str:
    path = project_root / "docs" / name
    if path not in _READ:
        _READ[path] = path.read_text(encoding="utf-8")
    return _READ[path]


def site_file(project_root: Path, name: str) -> dict:
    return json.loads((project_root / "outputs" / "site" / name).read_text(encoding="utf-8"))


def section(text: str, title: str, end: str | None = None) -> str:
    """The body of the second-level section `title`: up to `end` (its first appearance after the heading) when it is given, otherwise up to the next second-level heading."""
    body = text.split(f"\n## {title}\n", 1)[1]
    if end is not None:
        assert end in body, f"{end!r} does not follow the heading {title!r}"
        return body.split(end, 1)[0]
    return re.split(r"^## ", body, flags=re.MULTILINE)[0]


def decision(project_root: Path, number: int) -> str:
    return read(project_root, "decisions.md").split(f"\n## D{number:02d} ")[1].split("\n## D")[0]


def root_rows(project_root: Path) -> str:
    """The section of project 08 in the root ``SITE-UPDATES.md``, up to the end."""
    text = (project_root.parent / "SITE-UPDATES.md").read_text(encoding="utf-8")
    assert text.count("\n## 08 ") == 1, "SITE-UPDATES.md has no section for project 08"
    return text.split("\n## 08 ")[1]


OWNED = ("model-card.md", *DOCS)   # the documents U22 writes; research.md, requirements.md, plan.md and decisions.md are the planner's and the researcher's, and are not rewritten here


def all_documents(project_root: Path, readme: str) -> dict[str, str]:
    documents = {"README.md": readme, "SITE-UPDATES.md (08)": root_rows(project_root)}
    documents |= {f"docs/{name}": read(project_root, name) for name in OWNED}
    return documents


# --- the README and the model card (AC23, AC39) -----------------------------------------------------------------------------------------------------------------


def test_readme_headings_in_order_and_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    assert readme.startswith(README_TITLE + "\n")
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    head, rest = readme.split(RESULTS_START)
    block, tail = rest.split(RESULTS_END)
    block = block.strip("\n")
    # the block carries its own «## Resumen de la evaluación»: the headings of the plan are those outside it, in order
    assert re.findall(r"^## (.+)$", head + tail, flags=re.MULTILINE) == README_HEADINGS
    assert block == (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip("\n")   # what docs-sync copies, byte for byte
    assert block.startswith(RESULTS_HEADING + "\n") and re.findall(r"^## (.+)$", block, flags=re.MULTILINE) == ["Resumen de la evaluación"]
    framing = section(readme, "Los resultados", end=RESULTS_START)   # «Los resultados» frames the block before it and reads it after it
    assert len(framing.strip()) > 400 and "\n## En qué consiste\n" in tail
    # AC23: the sealed summary is unfavourable, and the README says «no se cumple» outside the block too, in the three sections that tell it
    assert summary["source"] == "warehouse" and summary["evaluation_status"] == "sealed" and "post_seal" not in summary   # the sealed result, with no analysis after the seal
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is None] == ["C10"]
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    assert "No se cumple: C03." in block
    reading = framing + tail.split("\n## En qué consiste\n")[0]
    for title, text in (("El problema", section(readme, "El problema")), ("La solución", section(readme, "La solución")), ("Los resultados", reading)):
        assert "no se cumple" in text.lower(), title
    for criterion in FAILED + PASSED:
        assert re.search(rf"\b{criterion}\b", reading), criterion
    assert "se esperaba" in reading.lower() and "no se mide el efecto" in reading.lower()   # the expectation of C03, and the first sentence of D16


def test_the_model_card_has_the_contents_of_the_plan_and_says_every_verdict(model_card: str, summary: dict) -> None:
    assert re.findall(r"^## (.+)$", model_card, flags=re.MULTILINE) == MODEL_CARD_HEADINGS
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in model_card, criterion["criterion_id"]   # every verdict as the summary writes it, «No se cumple» included
    for piece in (
        "UCI", "CC BY 4.0", "Chen", "hit@10", "als_128_r0.1_w1", "7 de recompra", "20 %", "CUPED", "A/A", "menor efecto detectable", "estratificada", "PeakWorkingSetSize", "180 s", "120 s", "100 s",
        "RNF02", "RNF03", "mlxtend", "implicit", "fa393815", "5ef462a0", "no se mide el efecto",
    ):
        assert piece.lower() in model_card.lower(), piece
    assert re.search(r"suite rápida[^\n]*\d{2,3},\d+ s", model_card)   # AC40: measured and written down


def test_the_documents_say_what_is_pending_and_the_open_findings(readme: str, model_card: str, project_root: Path) -> None:
    """RNF14: the independent evaluation, its corrections and the recheck of the corrections (L139) are done, so no document says the recheck is pending and each says it is done; the two findings of L133
    are told with their numbers and with what corrected them (D46, D49); ``docs/evaluation.md`` has its three parts; the seal and the credit of the source are complete; nothing local is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "todavía no" in text and ".pbix" in text and "no aplicado en el sitio todavía" in text
    assert "la comprobación de las correcciones está hecha" in text and "la comprobación de las correcciones están hechas" in model_card.lower()
    assert "ninguna cifra es definitiva" not in text and "ninguna cifra es definitiva" not in model_card.lower()
    for name, document in (("README.md", readme), ("docs/model-card.md", model_card), ("docs/review-advisories.md", read(project_root, "review-advisories.md"))):
        lowered = document.lower()
        assert "algorithms.json" in lowered and "5, 5 y 6" in lowered and "10 clientes" in lowered and "d46" in lowered, name   # the example lists: groups of 5, 5 and 6 under D30's 10, now aggregates
        assert "0,158" in lowered and "denominador" in lowered and "numerador" in lowered and "d49" in lowered, name   # C05: the distance with the plan's validation figure is mostly the numerator
    for name, document in (("README.md", readme), ("docs/model-card.md", model_card)):
        assert "5, 1 y 2" in document and "0,588" in document and "0,153" in document, name   # the evaluation's count within the profile, and C05 preregistered and with p01's definition
    evaluation = read(project_root, "evaluation.md")
    assert [title for title in ("La evaluación", "Las correcciones", "Comprobación") if f"\n## {title}\n" not in evaluation] == [] and "todavía no se hizo" not in section(evaluation, "Comprobación").lower()
    recheck = section(evaluation, "Comprobación")
    assert all(f"**N{n}." in recheck for n in range(1, 6)) and all(f"| B{n}," in recheck for n in range(1, 7)) and "Lo que queda" in recheck, "the recheck tells its six blockers and its five advisories"
    assert SEAL_SHA256 in readme and SEAL_SHA256[:8] in model_card and "5ef462a0" in readme
    tail = section(readme, "Fuente y licencia")
    for piece in ("Chen, D. (2012)", "Online Retail II", "UCI", "CC BY 4.0", "10.24432/C5CG6D", "572e3627", "implicit", "mlxtend", "MIT", "BSD"):
        assert piece in tail, piece
    for document in (readme, model_card):
        assert not LOCAL_PATH.search(document) and not any(name in EMAIL.sub("", document).lower() for name in USER_NAMES) and "@gmail" not in document


# --- the intervals the documents quote (AC39, RNF14) ------------------------------------------------------------------------------------------------------------

SIGN = "[+−-]?"
NUMBER = rf"({SIGN}\d+,\d+)"
INTERVAL_SCALE = {"C01": 100.0, "C02": 100.0, "C03": 100.0, "C04": 100.0}   # differences of proportions, in points


def quoted_bound(text: str) -> tuple[float, int]:
    """A bound as a document writes it («−1,9», «+23,1»): its value and its number of decimals."""
    sign, digits = (-1.0, text[1:]) if text[0] in "−-" else (1.0, text.lstrip("+"))
    return sign * float(digits.replace(",", ".")), len(digits.split(",")[1])


def test_every_quoted_interval_bound_equals_the_summary_at_its_decimals(project_root: Path, readme: str, model_card: str, summary: dict) -> None:
    """B3 of project 05: bounds rounded by hand came out wrong in two documents. Every interval of a criterion that has one (C01 to C04) that D19, the README, the model card and the root rows
    quote («intervalo del 95 %, A a B», «IC A a B» or «[A; B]») is the summary's, rounded to the decimals the document writes."""
    intervals = {c["criterion_id"]: (INTERVAL_SCALE[c["criterion_id"]] * c["ci_low"], INTERVAL_SCALE[c["criterion_id"]] * c["ci_high"]) for c in summary["criteria"] if c["ci_low"] is not None}
    assert sorted(intervals) == sorted(INTERVAL_SCALE)
    named = "|".join(intervals)
    interval = re.compile(rf"(?<![-–])\b({named})\b(?![-–])((?:(?!C\d\d)[^\n]){{0,300}}?)(?:intervalo del 95 %,? |IC |\[){NUMBER}(?: a |; ){NUMBER}")
    documents = {"D19": decision(project_root, 19), "README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (08)": root_rows(project_root)}
    wrong, seen = [], {}
    for name, text in documents.items():
        found = interval.findall(text)
        seen[name] = {criterion for criterion, *_rest in found}
        for criterion, _between, low, high in found:
            for written, value in ((low, intervals[criterion][0]), (high, intervals[criterion][1])):
                number, decimals = quoted_bound(written)
                if f"{number:.{decimals}f}" != f"{value:.{decimals}f}":
                    wrong.append(f"{name}: {criterion} writes {written}, the summary rounds to {value:.{decimals}f}")
    assert wrong == []
    assert set(intervals) == seen["docs/model-card.md"] and {"C01", "C02", "C04"} <= seen["README.md"] and {"C01", "C02", "C04"} <= seen["SITE-UPDATES.md (08)"], seen   # the check is not vacuous


# --- what the documents may not say: the effect of an offer (D16), a synthetic figure of real data, a customer number ------------------------------------------------

EFFECT_WORDS = re.compile(r"\befectos?\b|\buplift\b|\blift\b|\baumentos?\b", re.IGNORECASE)
ALLOWED_EFFECT = re.compile(
    r"menor efecto detectable|no se (?:puede |pudo )?(?:mide|medir|muestra|mostrar|dice|decir)\b[^.]{0,80}\befecto|\befecto\b[^.]{0,80}\bno (?:se )?(?:mide|puede|permite|muestra|dice)|"
    r"\bningún efecto\b|\bni (?:un |ningún )?efecto\b|\bsin (?:medir )?(?:ningún )?efecto|\bno (?:mide|mostrar|muestra|medir) (?:ningún )?efecto|no hay (?:un )?efecto|"
    r"\bninguna cifra\b[^.]{0,40}\bes (?:el |un )?efecto\b|\bno es (?:el |un )?efecto\b",   # the sentences D16 permits: «ninguna cifra es el efecto de una oferta», «esto no es un efecto»
    re.IGNORECASE,
)


def without_current_site_text(text: str) -> str:
    """The rows of ``SITE-UPDATES.md`` quote what the site says today in their third column («Hoy dice»), which is the text the row proposes to replace: that column is not this project's claim."""
    kept = []
    for line in text.splitlines():
        cells = line.split(" | ")
        kept.append(" | ".join(cells[:2] + cells[3:]) if re.match(r"^\| \d+ \|", line) and len(cells) >= 5 else line)
    return "\n".join(kept)


def sentences_of(text: str) -> list[str]:
    return [sentence for line in text.splitlines() for sentence in SENTENCE_END.split(line) if sentence.strip()]


def test_no_document_claims_an_offer_effect(project_root: Path, readme: str) -> None:
    """D16, AC23, plan 24.2: the archive has no offers, so no document says what an offer sells. «efecto», «aumento», «uplift» and «lift» appear only in a sentence that says no effect is measured
    (or names the minimum detectable effect), and the association rules' measure is ``rule_lift``."""
    offending, mentions = [], 0
    for name, text in all_documents(project_root, readme).items():
        for sentence in sentences_of(without_current_site_text(text).replace("rule_lift", "rule_measure")):
            if EFFECT_WORDS.search(sentence):
                mentions += 1
                if not ALLOWED_EFFECT.search(sentence) or re.search(r"\b(?:uplift|lift|aumentos?)\b", sentence, flags=re.IGNORECASE):
                    offending.append(f"{name}: {sentence.strip()[:160]}")
    assert offending == [] and mentions >= 8   # the documents do talk about it, in the permitted ways: the check is not vacuous
    assert "no se mide el efecto" in readme.lower()


SYNTHETIC_ALLOWED = re.compile(r"accesorio|modo rápido|ficticio|make-fixture|no (?:es|son|hay|está)[^.]{0,60}sintétic|«[^»]*sintétic[^»]*»|sustituto|de las pruebas", re.IGNORECASE)


def test_the_real_figures_are_not_called_synthetic(project_root: Path, readme: str) -> None:
    """The data of project 08 are the real public archive. «sintético» is for the test fixture and the quick mode (D44), never for a figure of the real run."""
    stray = [f"{name}: {line.strip()[:140]}" for name, text in all_documents(project_root, readme).items() for line in text.splitlines()
             if "sintétic" in line.lower() and not SYNTHETIC_ALLOWED.search(line)]
    assert stray == []
    assert "UCI" in readme and "datos reales" in readme.lower()


def test_no_document_names_a_customer_number(project_root: Path, readme: str) -> None:
    """D30, RNF12: every customer number of the archive has five digits from 12000 to 18999; no document holds a number in that range (product codes and counts have other shapes)."""
    found = [f"{name}: {number}" for name, text in all_documents(project_root, readme).items() for number in CUSTOMER_NUMBER.findall(text)]
    assert found == []


# --- the decisions, the stated test count, the memory figures, the tests the plan names, the log, the dictionary, the runbook, the step by step, the advisories, the
# links and the root rows (AC39) --------------------------------------------------------------------------------------------------------------------------------


def test_every_decision_has_seven_fields(project_root: Path) -> None:
    text = read(project_root, "decisions.md")
    entries = re.split(r"^## (?=D\d+ )", text, flags=re.MULTILINE)[1:]
    numbers = [int(re.match(r"D(\d+)", e).group(1)) for e in entries]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 45   # no gap and no repeat, up to the last decision of the build
    missing = [f"D{n:02d}: {field}" for n, entry in zip(numbers, entries, strict=True) for field in DECISION_FIELDS if f"- **{field}**: " not in entry]
    assert missing == []
    states = {f"D{n:02d}": re.search(r"^- \*\*Estado\*\*: (.+)$", e, flags=re.MULTILINE).group(1) for n, e in zip(numbers, entries, strict=True)}
    assert [d for d, s in states.items() if not re.match(r"(vigente|pendiente del dueño|reemplazada por D\d+)", s)] == []


def stated_count(request: pytest.FixtureRequest) -> str:
    """The test count as the documents write it, from the collection of this session; skipped when the session did not collect the default selection in full."""
    from tests.fixtures.suite_budget import is_full_default_selection

    if not is_full_default_selection(request.config):
        pytest.skip("the session did not collect the default selection in full: its collection is not the suite's count")
    return f"{len(request.session.items):,}".replace(",", ".") + " pruebas"


def test_stated_test_count_matches_the_session_collection(request: pytest.FixtureRequest, readme: str, model_card: str) -> None:
    """B3 of project 02, B5 of project 03 and B1 of project 04 (RNF14): the documents said one test count after a change had moved it. The count is that of the collection, in the README and the
    model card; the seconds next to it are measured and written by hand (AC40)."""
    stated = stated_count(request)
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", readme) == [stated]
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", section(model_card, "La suite rápida")) == [stated]


def test_every_memory_figure_names_its_counter(project_root: Path, readme: str) -> None:
    """RNF03 and D39 (lesson A3 of project 02): every sentence of the documents that gives a memory figure in MB or GB names the counter, by its API name or by what it counts."""
    absent = [f"docs/{name}" for name in DOCS if not (project_root / "docs" / name).is_file()]
    assert absent == [], "every document of AC39 that exists so far is there"
    figures, unnamed = 0, []
    for name, text in all_documents(project_root, readme).items():
        for line in text.splitlines():
            for sentence in SENTENCE_END.split(line):
                if MEMORY_FIGURE.search(sentence) and MEMORY_WORDS.search(sentence):
                    figures += 1
                    if not any(counter in sentence for counter in COUNTERS):
                        unnamed.append(f"{name}: {sentence.strip()[:160]}")
    assert unnamed == []
    assert figures >= 4   # the documents do state memory figures: the check is not vacuous


def test_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    """Plan 24.2, the class «documentación sin sincronizar»: the block is the summary of the sealed run, and the documents name the run and its seal."""
    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    assert block == (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip("\n")
    seal = json.loads((project_root / "reports" / "model_seal.json").read_text(encoding="utf-8"))
    assert summary["config_sha256"] in json.dumps(seal) and summary["config_sha256"][:8] == "5ef462a0"
    assert "5ef462a0" in readme and "5ef462a0" in read(project_root, "model-card.md")
    headline = summary["headline"]
    assert (headline["pairs"], headline["rounds"]) == (5803, 18) and "5.803" in readme and "5.803" in read(project_root, "model-card.md")


RENAMED = {   # four tests the plan names under another name or in another file; the writers of U14, U18, U19 and U20 gave them the name on the right, and plan.md is not rewritten after the build
    "tests/unit/test_reporting.py::test_the_summary_shows_the_quantity_the_threshold_tests":   # U14: it needs the sealed warehouse, so it lives with the integration tests of the summary
        "tests/integration/test_summary_after_seal.py::test_the_summary_shows_the_quantity_the_threshold_tests",
    "tests/unit/test_lock.py::test_the_folders_it_created_are_removed_when_empty":   # U18: the longer name says when it is true
        "tests/unit/test_lock.py::test_the_folders_the_lock_created_are_removed_with_it_when_nothing_was_written_in_them",
    "tests/unit/test_compose.py::test_the_init_script_stops_at_the_first_failure_and_has_no_carriage_return_in_bytes":   # U20: the script is read in bytes by the shared ``init_script`` fixture, which that test asserts
        "tests/unit/test_compose.py::test_the_init_script_stops_at_the_first_failure",
    "tests/e2e/test_airflow_docker.py::test_dags_test_twice_in_quick_mode_and_leaves_nothing_behind":   # U20: the quick mode delivers to the CRM (plan section 22), and the test says the CRM answers
        "tests/e2e/test_airflow_docker.py::test_dags_test_twice_in_quick_mode_the_crm_answers_and_nothing_is_left_behind",
}


def named_in_plan(plan: str) -> list[tuple[str, str]]:
    """Every test the plan names, as (file, function): a bare ``::name`` belongs to the file named last before it."""
    found, last = [], None
    for match in NAMED_TEST.finditer(plan):
        last = match.group(1) or last
        assert last is not None, match.group(0)
        found.append((last, match.group(2)))
    return found


def test_every_test_named_in_the_plan_exists(project_root: Path) -> None:
    """AC39: every test plan sections 24 and 27 name (the RED of each unit and the named defect classes) is a test function of that file."""
    named = named_in_plan(read(project_root, "plan.md"))
    assert len(named) >= 100   # the plan does name its tests: the check is not vacuous
    defined: dict[str, set[str]] = {}
    missing = []
    for path, name in named:
        path, name = RENAMED.get(f"{path}::{name}", f"{path}::{name}").split("::")
        if path not in defined:
            file = project_root / path
            tree = ast.parse(file.read_text(encoding="utf-8")) if file.is_file() else ast.Module(body=[], type_ignores=[])
            defined[path] = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if name not in defined[path]:
            missing.append(f"{path}::{name}")
    assert sorted(set(missing)) == []


def log_entries(project_root: Path) -> dict[int, str]:
    """The entries L117 and later of the tracking document at the root of the repository, by number (skipped when the repository has no such document)."""
    path = project_root.parent / LOG
    if not path.is_file():
        pytest.skip("the tracking document is not next to the project")
    parts = re.split(r"^- \*\*L(\d+) ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)[1:]
    return {int(number): body for number, body in zip(parts[::2], parts[1::2], strict=True) if int(number) >= FIRST_LOG_ENTRY}


def test_every_unit_the_docs_tell_has_its_log_entry(project_root: Path, readme: str) -> None:
    """B4 and N2 of project 05 (RNF14): the documents told units and corrections that the log did not have yet. Every unit (U01...) and every entry (L117...) that the README, the step by step and
    the advisories name is in the log, and the step by step names every unit and every entry the log has."""
    entries = log_entries(project_root)
    assert max(entries) >= 134 and sorted(entries) == list(range(FIRST_LOG_ENTRY, max(entries) + 1))   # the log of project 08 is there, with no gap
    logged_units = {unit for body in entries.values() for unit in re.findall(r"\bU\d{2}\b", body)}
    assert set(UNITS_DONE) <= logged_units
    documents = {"README.md": readme, "docs/paso-a-paso.md": read(project_root, "paso-a-paso.md"), "docs/review-advisories.md": read(project_root, "review-advisories.md")}
    told = {name: set(re.findall(r"\bU\d{2}\b", text)) for name, text in documents.items()}
    assert [(name, sorted(units - logged_units)) for name, units in told.items() if units - logged_units] == []   # no unit the log lacks
    cited = {name: {int(n) for n in re.findall(r"\bL(\d{2,3})\b", text)} for name, text in documents.items()}
    assert [(name, sorted(numbers - set(entries))) for name, numbers in cited.items() if numbers - set(entries)] == []   # no entry the log lacks
    assert set(UNITS_DONE) <= told["docs/paso-a-paso.md"]   # the step by step names every unit the log has
    assert set(range(FIRST_LOG_ENTRY, 135)) <= cited["docs/paso-a-paso.md"]   # and every entry of the project up to the review of U21


def test_the_dictionary_covers_the_sources_and_its_tables_are_the_generated_ones(project_root: Path) -> None:
    import pyarrow.parquet as pq

    from personaloffers.base import COVARIATE_COLUMNS
    from personaloffers.config import load_config
    from personaloffers.dashboard.semantic_model import MODEL, arrow_schema
    from personaloffers.docs_sync import END, START, dictionary_block
    from personaloffers.lines import ROLES
    from personaloffers.offers import SOURCES

    cfg = load_config(project_root / "config" / "pipeline.toml")
    text = read(project_root, "data-dictionary.md")
    source = section(text, "Las 8 columnas de la fuente")
    assert re.findall(r"^\| `([A-Za-z ]+)` \|", source, flags=re.MULTILINE) == list(cfg.source.columns) and len(cfg.source.columns) == 8
    roles = section(text, "Los roles de línea")
    assert re.findall(r"^\| \d \| `([a-z_]+)` \|", roles, flags=re.MULTILINE) == list(ROLES)
    base = section(text, "La base de contactos y las covariables")
    assert re.findall(r"^\| `([a-z_0-9]+)` \|", base, flags=re.MULTILINE)[: len(COVARIATE_COLUMNS)] == list(COVARIATE_COLUMNS)
    origins = section(text, "Los orígenes de cada producto de la lista")
    assert re.findall(r"^\| `([a-z]+)` \|", origins, flags=re.MULTILINE) == list(SOURCES)
    generated = section(text, "Las tablas del modelo estrella")
    assert re.findall(r"^### `([a-z_]+)`$", generated, flags=re.MULTILINE) == [t.name for t in MODEL.tables] and len(MODEL.tables) == 25
    public = project_root / "outputs" / "powerbi"
    for table in MODEL.tables:
        assert text.count(START.format(name=table.name)) == 1 and text.count(END.format(name=table.name)) == 1, table.name
        block = text.split(START.format(name=table.name))[1].split(END.format(name=table.name))[0]
        assert block.strip() == dictionary_block(table).strip(), table.name   # what docs_sync writes
        listed = re.findall(r"^\| `([a-z_0-9]+)` \| ", block, flags=re.MULTILINE)
        assert tuple(listed) == table.column_names, table.name
        if (public / f"{table.name}.parquet").is_file():   # the one private table (the list of each customer) is not versioned
            assert pq.read_schema(public / f"{table.name}.parquet").names == list(table.column_names) == arrow_schema(table).names, table.name
    assert len([t for t in MODEL.tables if (public / f"{t.name}.parquet").is_file()]) == 24


RUNBOOK_TOPICS = {   # what each entry has to be about (the refusal messages of the code point here)
    1: ("s00_download.py", "SHA-256", "online_retail_ii.zip"), 2: ("V03", "libro", "hoja"), 3: ("V10", "rechaz", "load"), 4: ("entrega", "orden", "V10"), 5: ("M04", "ValidationLeakError", "memoria"),
    6: ("huella", ".npy", "--from fit_recipe"), 7: ("sello", "config_sha256", "SealMismatchError"), 8: ("bloqueo", "PERSONALOFFERS_", "exit 2"), 9: ("CRM", "token", "409"),
    10: ("Airflow", "Docker", "libgomp1"), 11: ("desde cero", "raw/deliveries", "adopt"), 12: ("análisis nuevo", "sello", "carpeta"),
}


def test_the_runbook_has_r1_to_r12_and_every_reference_of_the_code_points_to_one(project_root: Path) -> None:
    text = read(project_root, "runbook.md")
    entries = re.split(r"^## (?=R\d+ )", text, flags=re.MULTILINE)[1:]
    assert [entry.split()[0] for entry in entries] == [f"R{n}" for n in range(1, 13)]   # plan, section 25
    for entry in entries:
        assert "**Síntoma.**" in entry and "**Qué hacer.**" in entry, entry.splitlines()[0]
    for number, words in RUNBOOK_TOPICS.items():
        entry = entries[number - 1]
        assert [word for word in words if word.lower() not in entry.lower()] == [], f"R{number}"
    sources = [*sorted((project_root / "src" / "personaloffers").rglob("*.py")), *sorted((project_root / "airflow").rglob("*.py")), project_root / "airflow" / "docker-compose.yaml"]
    cited = {int(n) for path in sources for n in re.findall(r"runbook(?:\.md)?,? R(\d+)", path.read_text(encoding="utf-8"))}
    assert {1, 3, 5, 6, 7, 8, 11, 12} <= cited <= set(range(1, 13)), cited   # every entry the code points to exists and is about that
    rebuild = entries[10]
    for step in ("data/warehouse/", "data/interim/", "data/raw/deliveries/", "data/crm/standin.sqlite"):
        assert step in rebuild, step   # the four things R11 moves aside, as the rebuild test moves them (tests/e2e/test_rebuild.py)
    for kept in ("reports/model_seal.json", "data/models/", "data/raw/online_retail_ii.zip"):
        assert kept in rebuild, kept   # and the three it keeps


def test_the_step_by_step_names_every_unit_and_cites_commits_that_exist(project_root: Path) -> None:
    text = read(project_root, "paso-a-paso.md")
    assert [unit for unit in UNITS_DONE if not re.search(rf"\b{unit}\b", text)] == []
    hashes = sorted(set(re.findall(r"`([0-9a-f]{7})`", text)))
    assert len(hashes) >= 43   # the 43 commits of the project up to the real run, and more
    if shutil.which("git") is None or not (project_root.parent / ".git").exists():
        pytest.skip("there is no Git history to check the commits against")
    done = subprocess.run(["git", "cat-file", "--batch-check"], cwd=project_root, input="".join(f"{h}^{{commit}}\n" for h in hashes), capture_output=True, text=True)
    assert [line for line in done.stdout.splitlines() if line.endswith("missing")] == []
    # the chronology is whole: every commit of the project up to the real run (U21) is in it
    history = subprocess.run(["git", "log", "--abbrev=7", "--format=%h", "e9ca105", "--", "."], cwd=project_root, capture_output=True, text=True)
    assert history.returncode == 0 and len(history.stdout.split()) == 43 and [h for h in history.stdout.split() if h not in hashes] == []


def test_relative_links_and_images_point_to_files_that_exist(project_root: Path, readme: str) -> None:
    """Every relative link and image of the README and of the documents resolves, and the README links to every document of ``docs/`` that exists."""
    broken = []
    for document in [project_root / "README.md", *sorted((project_root / "docs").glob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for target in [*LINK.findall(text), *IMAGE.findall(text)]:
            if not re.match(r"^(https?:|mailto:)", target) and not (document.parent / target).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []
    unlinked = [f"docs/{name}" for name in ("research.md", "requirements.md", "plan.md", "decisions.md", "model-card.md", *DOCS) if f"](docs/{name})" not in readme]
    assert unlinked == []
    figures = sorted(path.name for path in (project_root / "docs" / "figures").glob("*.png"))
    assert [name for name in figures if f"](docs/figures/{name})" not in readme] == []   # every figure that exists is shown


def advisories(text: str) -> dict[tuple[str, str], str]:
    """Every advisory of the review file by (section key, id), with its status: the bold words after «Estado:», or an empty string."""
    found: dict[tuple[str, str], str] = {}
    for part in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        key = part.split()[0]
        for block in re.split(r"^(?=- \*\*)", part, flags=re.MULTILINE)[1:]:
            ident = re.match(r"- \*\*([^*]+)\*\*", block).group(1)
            status = re.search(r"^  - Estado: \*\*([^*]+)\*\*", block, flags=re.MULTILINE)
            assert (key, ident) not in found, (key, ident)
            found[(key, ident)] = status.group(1) if status else ""
    return found


ADVISORIES_IN_ALL = 26   # L122 (2), L126 (7), L128 (14), L130 (2) and the review of U21 (1): the bullets of the log that hold several findings are told one by one


def test_open_advisories_match_review_file(project_root: Path, readme: str) -> None:
    """AC39 and B5 of project 03's evaluation: every finding of every native review of project 08 (L122 to L130 and L134, the review of U21) has its location and its status in
    ``docs/review-advisories.md``, the count the documents give is the number of blocks, and the number of open ones the README states is the number the file calls open."""
    text = read(project_root, "review-advisories.md")
    found = advisories(text)
    assert len(found) == ADVISORIES_IN_ALL and [key for key, status in found.items() if status not in STATUSES] == []
    blocks = [block for block in re.split(r"^(?=- \*\*)", text, flags=re.MULTILINE) if block.startswith("- **")]
    assert len(blocks) == ADVISORIES_IN_ALL and all(re.search(r"^  - Ubicación: .+", block, flags=re.MULTILINE) for block in blocks)   # where each one is
    fixed = [block for block in blocks if "Estado: **corregida**" in block]
    assert all(re.search(r"`[0-9a-f]{7}`", block.split("Estado: **corregida**")[1].splitlines()[0]) for block in fixed)   # each with its commit
    left = [block for block in blocks if re.search(r"Estado: \*\*(dejada con evidencia|refutada)\*\*\. \S", block)]
    opened = [block for block in blocks if "Estado: **abierta**" in block]
    assert len(fixed) + len(left) + len(opened) == ADVISORIES_IN_ALL and all(re.search(r"Estado: \*\*abierta\*\*\. \S", block) for block in opened)
    [stated] = re.findall(r"^Advertencias abiertas: (\d+)\b", readme, flags=re.MULTILINE)
    assert int(stated) == len(opened) and len(opened) >= 1   # the three suggestions L131 left out are open; the finding of D30 was corrected with D46
    for number in (f"{ADVISORIES_IN_ALL} en total", f"{ADVISORIES_IN_ALL} hallazgos"):
        assert number in text or number in readme or number in read(project_root, "paso-a-paso.md"), number
    for document in (readme, read(project_root, "paso-a-paso.md"), read(project_root, "model-card.md")):
        assert not re.search(rf"\b(?!{ADVISORIES_IN_ALL}\b)\d{{2}} (?:hallazgos|advertencias en total)", document), "a document gives another total than the file"
    # what could not be reviewed is said: the units under budget, the generated commit over it, and the review of U21 with its escalation
    for piece in ("under_budget", "u02", "u03", "u05", "u07", "f1", "f2", "u19", "s3", "e9ca105", "7238720..f8f80b5"):
        assert piece in text, piece


STALE_PENDING = re.compile(r"ninguna cifra es definitiva|la comprobaci[oó]n de las correcciones[^.\n]{0,40}\bfalta\b|pendiente de la (?:evaluaci|comprobaci)|\*\*Pendiente\.\*\*|revisi[oó]n(?:es)? de U2[12][^.\n]{0,40}pendientes?", flags=re.IGNORECASE)


def test_no_document_says_the_evaluation_is_pending_after_it_was_done(project_root: Path, readme: str) -> None:
    """Plan, section 28.4, and B4 and N1 of project 05 (RNF14): the independent evaluation of project 08 is not done yet, so ``docs/evaluation.md`` does not exist and the documents say it is
    pending; once it exists, no document says it is. The reviews of U21 are done and no document says they are pending."""
    documents = all_documents(project_root, readme)
    stale = [f"{name}: {match.group(0)}" for name, document in documents.items() for match in STALE_PENDING.finditer(document)]
    assert stale == []
    done = (project_root / "docs" / "evaluation.md").is_file()
    says_pending = [name for name in ("README.md", "docs/paso-a-paso.md") if re.search(r"evaluación independiente[^.\n]{0,160}todavía no", documents[name], flags=re.IGNORECASE)]
    assert (says_pending == []) == done, "the documents say the evaluation is pending exactly while docs/evaluation.md does not exist"


def test_the_root_rows_of_project_08_carry_the_real_figures(project_root: Path) -> None:
    rows = root_rows(project_root)
    table = [line for line in rows.split("### ")[0].splitlines() if re.match(r"^\| \d+ \|", line)]
    assert [int(line.split("|")[1]) for line in table] == list(range(1, 15))   # plan, section 30: the fourteen rows
    for figure in ("78,0", "52,9", "79,2", "25,1", "23,1", "26,9", "−1,2", "−1,9", "−0,4", "33,8", "28,1", "5,8", "4,6", "7,0", "0,559", "0,048", "4,8", "6,2", "0,294", "0,735", "65.959", "0,76", "227,83",
                   "fa393815", "5ef462a0", "als_128_r0.1_w1", "22.523", "173", "5, 5 y 6", "0,158"):
        assert figure in rows, figure
    assert rows.count("No se cumple") >= 1 and all(f"C{n:02d}" in rows for n in range(1, 10)) and "PeakWorkingSetSize" in rows
    assert "No aplicado en el sitio todavía" in rows and "Aplicado en el sitio" not in rows.replace("No aplicado en el sitio", "") and "personal-offers" in rows and "Airflow" in rows and "@gmail" not in rows
    assert "n8n" not in rows.replace("n8n por Airflow", "").replace("n8n (si algún texto lo conserva)", "") or "Airflow" in rows
    assert "no se mide el efecto" in rows.lower() or "no se muestra ningún efecto" in rows.lower()
    assert not LOCAL_PATH.search(rows) and "Users" not in rows


def test_the_landing_expansion_has_the_rows_of_project_08(project_root: Path) -> None:
    """D34: the rows U01 left owed (``PENDING_LANDING_ROWS``, now empty) name project 08, and project 08 is added to the rows of the technologies it shares."""
    text = (project_root.parent / "LANDING-EXPANSION.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if re.match(r"^\| [^|]+ \|", line)}
    for technology in ("NumPy", "SQLite", "Apache Parquet con pyarrow", "matplotlib", "pytest", "PostgreSQL", "SciPy", "openpyxl", "uvicorn", "httpx"):
        assert "08 Una oferta para cada cliente" in rows[technology], technology
    names = " ".join(name.lower() for name in rows)
    assert [pin for pin in ("implicit", "mlxtend") if pin not in names] == []
    for new in ("implicit", "mlxtend"):
        [row] = [line for name, line in rows.items() if new in name.lower()]
        assert "08 Una oferta para cada cliente" in row and "D09" in row, new
    assert re.search(r"^PENDING_LANDING_ROWS = frozenset\(\)$", (project_root / "tests" / "unit" / "test_dependencies.py").read_text(encoding="utf-8"), flags=re.MULTILINE)


def tracked_text_files(project_root: Path) -> list[Path]:
    if shutil.which("git") is None or not (project_root.parent / ".git").exists():
        pytest.skip("there is no Git history to list the tracked files")
    listed = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=project_root, capture_output=True)
    assert listed.returncode == 0
    files = [project_root / name for name in listed.stdout.decode("utf-8").split("\0") if name]
    return [path for path in files if path.suffix.lower() in {".md", ".py", ".txt", ".toml", ".json", ".out", ".sql", ".yaml", ".yml", ".html", ".sh", ".cfg", ".ini", ".example"} or path.name in {".gitignore", "Dockerfile"}]


def test_no_tracked_text_file_names_a_local_user_folder(project_root: Path, readme: str) -> None:
    """Plan 24.2 (05 D43; 07 ``da355b7``): no versioned text file of the project, research outputs included, and no root document it adds to, names a path of this machine or its user."""
    files = tracked_text_files(project_root)
    assert len(files) >= 150   # the check is not vacuous
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if TRACKED_PATH.search(text) or any(user in EMAIL.sub("", text).lower() for user in USER_NAMES):
            found.append(path.relative_to(project_root).as_posix())
    assert found == []


def test_no_document_publishes_a_local_path_or_a_user_name(project_root: Path, readme: str) -> None:
    """The README, every document of ``docs/`` and the root rows name no path of the machine and no user name."""
    found = [name for name, text in all_documents(project_root, readme).items() if LOCAL_PATH.search(text) or any(user in EMAIL.sub("", text).lower() for user in USER_NAMES)]
    assert found == []


def _pct(value: float) -> str:
    return f"{value * 100:,.1f} %".replace(",", "§").replace(".", ",").replace("§", ".")


def test_the_method_table_of_the_model_card_is_the_one_of_the_site_file(project_root: Path, model_card: str) -> None:
    """Each row of the table of the methods is ``algorithms.json`` (the hit rate and its interval of the 18 rounds, both variants, the coverage), at the decimals the card writes."""
    methods = site_file(project_root, "algorithms.json")["methods"]
    lines = model_card.splitlines()
    by_key = {(m["method_key"], m["variant_key"]): m for m in methods}
    order = ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "chosen_discovery", "offer_list"]
    checked = 0
    for key in order:
        every, new = by_key.get((key, "unrestricted")), by_key.get((key, "new_only"))
        label = (every or new)["label_es"]
        cells = [label]
        for method in (every, new):
            cells += ["—", "—", "—"] if method is None else [_pct(method["hit_rate"]), f"{_pct(method['ci_low'])} a {_pct(method['ci_high'])}", f"{method['coverage']:.3f}".replace(".", ",")]
        row = "| " + " | ".join(cells) + " |"
        assert row in lines, row
        checked += 1
    assert checked == 9 and all(m["pairs"] == 5803 for m in methods)


TABLE_DELIMITER = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _cells(line: str) -> int:
    return len(re.split(r"(?<!\\)\|", line.strip().removeprefix("|").removesuffix("|")))


def test_every_markdown_table_row_has_the_header_width(project_root: Path, readme: str) -> None:
    """06's L84: a table with a delimiter row of other width than its header does not render on GitHub. Every table of the README and of ``docs/``, generated or written by hand, has as many cells
    in its delimiter and in each of its rows as in its header."""
    documents = {"README.md": readme} | {f"docs/{p.name}": read(project_root, p.name) for p in sorted((project_root / "docs").glob("*.md"))}
    broken, tables = [], 0
    for name, text in documents.items():
        lines, fenced = text.splitlines(), False
        for at, line in enumerate(lines):
            fenced = fenced != line.startswith("```")
            if fenced or not TABLE_DELIMITER.match(line):
                continue
            tables += 1
            width = _cells(lines[at - 1])
            rows = lines[at:]
            body = rows[: next((k for k, row in enumerate(rows) if not row.startswith("|")), len(rows))]
            broken += [f"{name}:{at + 1 + k}" for k, row in enumerate(body) if _cells(row) != width]
    assert broken == [] and tables >= 30


CONTROL_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # everything but \t, \n and (in a CRLF pair) \r


def test_no_tracked_markdown_holds_a_control_byte(project_root: Path) -> None:
    """N1 of project 07's recheck: a Windows path written in a script string lost its backslashes («data\\raw\\» became a carriage return and «aw\\») and R11 step 1 named paths that do not exist. No
    Markdown file of the README or ``docs/`` holds a control byte other than a tab and a line break (a carriage return only as the first half of CRLF)."""
    files = [project_root / "README.md", *sorted((project_root / "docs").glob("*.md"))]
    assert len(files) >= 8
    found = []
    for path in files:
        data = path.read_bytes()
        lone_cr = re.sub(rb"\r\n", b"", data).count(b"\r")
        found += [f"{path.name}: {hit.group(0)!r} at {hit.start()}" for hit in CONTROL_BYTES.finditer(data)]
        found += [f"{path.name}: {lone_cr} lone carriage return(s)"] * bool(lone_cr)
    assert found == []
