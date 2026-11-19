"""``airflow dags test`` in Docker, twice, in quick mode, and the CRM service (U20, AC35; RNF04; plan section 22; D26). Mark ``docker``: not in the default selection, and skipped unless the Docker engine is
running. Adapted from project 07's ``tests/e2e/test_airflow_docker.py``.

Run it with ``pytest -m docker``. It builds the image of ``airflow/`` (several minutes the first time), runs ``pip check`` and the imports of the pipeline in it (implicit needs a wheel for the image: the build
fails if there is none), starts the database and the initialization service of the compose file, runs the DAG ``personaloffers_weekly`` on the synthetic workbook twice in a row and checks that the first run is
the launch and the second the first weekly delivery, that what the launch sealed (the seal and the registered models) did not change between them, that the second run delivered its lists to the CRM stand-in
and that the CRM holds each list once. The ``crm`` service is started too and asked, from inside the network of the project, what it answers without the token and with it. It writes only inside
``data/quick/`` (git-ignored), the ``airflow/logs``, ``airflow/config`` and ``airflow/plugins`` folders the containers use and the empty ``data/raw``, ``outputs``, ``reports`` and ``dashboard`` folders that the
mounts create when they are missing, with throwaway secrets passed through the environment (the five of the compose file, the password of the metadata database included).

What it creates it removes, also when it fails (A13 of project 04's evaluation): the stack with its database volume and its network (``docker compose down --volumes``), the image
``personaloffers-airflow:3.4.0`` and the two external images when this test pulled or built them (an image that was there before the test stays), and the folders above. It refuses to start when the compose
project already has containers, volumes or networks, so it never removes what another run left; the build cache of Docker is not an image, a volume or a network and is not touched.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.make_workbook import make_workbook

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
QUICK = PROJECT / "data" / "quick"
CREATED = ("logs", "config", "plugins")                       # folders of airflow/ that the bind mounts create
MOUNTED = ("data/raw", "data", "outputs", "reports", "dashboard")   # folders of the project that the mounts create when they are missing (children first)
IMAGE = "personaloffers-airflow:3.4.0"                        # the compose file's image of the services (tests/unit/test_compose.py checks the name)
PROJECT_NAME = "personaloffers-airflow"                       # the compose file's ``name``: the label of everything the stack creates
EXTERNAL = (                                                   # the two images the build and the stack pull, by version and digest (projects 04 to 07's, D26)
    "apache/airflow:3.4.0@sha256:a8d9d19c563c768b2bc605ef26440f28a9164ea886064e99c599b057432ff572",
    "postgres:16.9@sha256:ddfe3e8713e3ee5b8f286082cb12512488dfbf3f5a1ecb0b74a42e6055af0a5f",
)
DOWN = ("compose", "--profile", "debug", "down", "--volumes")   # the profile of the service this test starts: ``down`` only knows the ones it is told
QUICK_CONFIG = "/opt/personaloffers/config/pipeline.quick.toml"
LAUNCH_ID, FIRST_WEEKLY_ID = "L2011-03-27", "W2011-03-28"        # the plan of the quick configuration: the launch and the first weekly delivery
BUILD_TIMEOUT_S = 1800
STEP_TIMEOUT_S = 900
TEARDOWN_TIMEOUT_S = 300

pytestmark = pytest.mark.docker

CURRENT: dict[str, str] = {}   # the secrets of the running test, the same for every docker call of it


def throwaway_secrets() -> dict[str, str]:
    """The five secrets of the compose file, new for each test: it has no default for any (AC35)."""
    return {
        "PERSONALOFFERS_DB_PASSWORD": secrets.token_hex(24),
        "PERSONALOFFERS_FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "PERSONALOFFERS_JWT_SECRET": secrets.token_urlsafe(48),
        "PERSONALOFFERS_ADMIN_PASSWORD": secrets.token_urlsafe(16),
        "PERSONALOFFERS_CRM_TOKEN": secrets.token_urlsafe(32),
    }


def docker(*args: str, timeout: int = STEP_TIMEOUT_S, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    environment = {**os.environ, **(CURRENT if env is None else env), "PERSONALOFFERS_CONFIG": QUICK_CONFIG}
    try:
        return subprocess.run(["docker", *args], cwd=AIRFLOW, env=environment, capture_output=True, text=True, timeout=timeout, check=check, encoding="utf-8")
    except subprocess.TimeoutExpired as error:
        pytest.fail(f"docker {' '.join(args)} did not end in {timeout} s:\n" + str(error.stdout or "")[-1500:] + str(error.stderr or "")[-1500:])


def rows(query: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"{(QUICK / 'personaloffers.sqlite').as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def crm_rows(query: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"{(QUICK / 'crm.sqlite').as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def image_exists(reference: str) -> bool:
    return docker("image", "inspect", reference, check=False).returncode == 0


def leftovers() -> dict[str, list[str]]:
    """What the compose project owns on this machine, by its label: nothing before the test and nothing after its teardown."""
    label = f"label=com.docker.compose.project={PROJECT_NAME}"
    kinds = {"containers": ("ps", "-a", "-q"), "volumes": ("volume", "ls", "-q"), "networks": ("network", "ls", "-q")}
    return {kind: docker(*command, "--filter", label, check=False).stdout.split() for kind, command in kinds.items()}


def teardown(existing: set[str], existing_mounts: set[str], *, image_existed: bool, external_existed: tuple[str, ...] = ()) -> list[str]:
    """Remove the stack with its volume and network, the image this test built (`image_existed` False), the external images it pulled (those not in `external_existed`), the folders it created; return what
    could not be done. Each step is tried even if another failed."""
    problems: list[str] = []

    def attempt(what: str, *args: str) -> None:
        try:
            done = docker(*args, check=False, timeout=TEARDOWN_TIMEOUT_S)
            if done.returncode != 0:
                problems.append(f"{what} returned {done.returncode}:\n" + (done.stdout + done.stderr)[-2000:])
        except (Exception, pytest.fail.Exception) as error:
            problems.append(f"{what} did not finish: {error}")

    attempt("docker compose down --volumes", *DOWN)
    if not image_existed:
        attempt(f"docker image rm {IMAGE}", "image", "rm", IMAGE)   # before the bases: it is built on one of them
    for reference in EXTERNAL:
        if reference not in external_existed:
            attempt(f"docker image rm {reference}", "image", "rm", reference)
    for folder in [QUICK] + [AIRFLOW / name for name in CREATED if name not in existing]:
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            problems.append(f"{folder} could not be removed")
    for name in MOUNTED:
        folder = PROJECT / name
        if name not in existing_mounts and folder.exists():
            try:
                folder.rmdir()
            except OSError:
                problems.append(f"{folder} was created by the mounts and is not empty: {sorted(p.name for p in folder.iterdir())[:5]}")
    return problems


def dags_test() -> subprocess.CompletedProcess:
    return docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "airflow", "dags", "test", "personaloffers_weekly", check=False)


def inside(code: str) -> subprocess.CompletedProcess:
    """Python `code` in a container of the project's network (the debug service), where the services are reached by name."""
    return docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "python", "-c", code, check=False)


def folder_bytes(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def make_quick_source() -> None:
    """The synthetic workbook that the quick configuration reads under ``data/quick`` (what ``python -m personaloffers make-fixture data/quick/online_retail_fixture.zip`` writes)."""
    make_workbook(QUICK)


@pytest.fixture(autouse=True)
def secrets_of_this_test():
    CURRENT.clear()
    CURRENT.update(throwaway_secrets())
    yield
    CURRENT.clear()


@pytest.fixture()
def engine():
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("the Docker engine is not running")


def test_the_compose_file_needs_each_secret_and_puts_the_database_password_in_the_connection_string(engine) -> None:
    """Without one secret (or with it empty) the file does not render and names it; with all five, the connection string and the PostgreSQL service carry the database password. Nothing is built or
    started."""
    given = dict(CURRENT)
    rendered = docker("compose", "config", env=given, check=False)
    assert rendered.returncode == 0, rendered.stderr[-2000:]
    assert f"postgresql+psycopg://airflow:{given['PERSONALOFFERS_DB_PASSWORD']}@postgres/airflow" in rendered.stdout
    assert f"POSTGRES_PASSWORD: {given['PERSONALOFFERS_DB_PASSWORD']}" in rendered.stdout
    assert re.search(r"target: /opt/personaloffers/data/raw\s+read_only: true", rendered.stdout), "the UCI zip is mounted read-only"
    for name in given:
        missing = docker("compose", "config", env={k: v for k, v in given.items() if k != name}, check=False)
        assert missing.returncode != 0 and name in missing.stderr, (name, missing.stderr[-800:])
        blank = docker("compose", "config", env={**given, name: ""}, check=False)
        assert blank.returncode != 0 and name in blank.stderr, (name, "empty", blank.stderr[-800:])


def test_dags_test_twice_in_quick_mode_the_crm_answers_and_nothing_is_left_behind(engine) -> None:
    """AC35: the image passes ``pip check`` (judged by its exit code, not by a text of its output) and imports the pipeline and implicit; ``airflow dags test personaloffers_weekly`` runs the launch and then
    the first weekly delivery with the seal of the launch unchanged, the second run delivers its lists to the CRM stand-in and the CRM holds each list once; the ``crm`` service refuses a request without the
    token and answers one with it. The teardown (A13) leaves no container, volume or network of the project and no image this test created."""
    assert not QUICK.exists(), "data/quick is left over from another run (run `docker compose down --volumes` in airflow/ and delete it)"
    assert leftovers() == {"containers": [], "volumes": [], "networks": []}, "the compose project already exists: this test would remove what it did not create"
    existing = {name for name in CREATED if (AIRFLOW / name).exists()}
    existing_mounts = {name for name in MOUNTED if (PROJECT / name).exists()}
    image_existed = image_exists(IMAGE)
    external_existed = tuple(reference for reference in EXTERNAL if image_exists(reference))
    try:
        QUICK.mkdir(parents=True)
        make_quick_source()
        for step in (("compose", "build"), ("compose", "up", "airflow-init")):
            done = docker(*step, check=False, timeout=BUILD_TIMEOUT_S if step[1] == "build" else STEP_TIMEOUT_S)
            assert done.returncode == 0, f"docker {' '.join(step)} failed:\n" + (done.stdout + done.stderr)[-3000:]
        check = "pip check && python -c 'import pandas, pyarrow, scipy, implicit, openpyxl, matplotlib, fastapi, uvicorn, httpx; import personaloffers.pipeline, personaloffers.crm.standin'"
        consistent = docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "bash", "-c", check, check=False)
        assert consistent.returncode == 0, (consistent.stdout + consistent.stderr)[-2000:]

        service = docker("compose", "up", "-d", "crm", check=False)
        assert service.returncode == 0, (service.stdout + service.stderr)[-2000:]
        probe = ("import httpx, os, time\n"
                 "def ask(url, headers=None, tries=30):\n"
                 "    for _ in range(tries):\n"
                 "        try:\n"
                 "            return httpx.get(url, headers=headers or {}, timeout=5).status_code\n"
                 "        except httpx.TransportError:\n"
                 "            time.sleep(2)\n"
                 "    return None\n"
                 "token = os.environ['PERSONALOFFERS_CRM_TOKEN']\n"
                 "print('crm', ask('http://crm:8001/health'), ask('http://crm:8001/health', {'Authorization': 'Bearer ' + token}))\n")
        answered = inside(probe)
        assert answered.returncode == 0 and "crm 401 200" in answered.stdout, (answered.stdout + answered.stderr)[-2000:]

        first = dags_test()
        assert first.returncode == 0, first.stdout[-3000:] + first.stderr[-3000:]
        seal_path = QUICK / "reports" / "model_seal.json"
        registry = "SELECT round_id, component, artifact_sha256 FROM model_registry ORDER BY 1, 2"
        launch_models, launch_seal = rows(registry), seal_path.read_bytes()
        assert [r[0] for r in rows("SELECT delivery_id FROM pipeline_runs WHERE delivery_id IS NOT NULL ORDER BY as_of")] == [LAUNCH_ID]
        assert launch_models and launch_seal

        second = dags_test()
        assert second.returncode == 0, second.stdout[-3000:] + second.stderr[-3000:]
        assert rows("SELECT delivery_id, status FROM pipeline_runs WHERE delivery_id IS NOT NULL ORDER BY as_of") == [(LAUNCH_ID, "ok"), (FIRST_WEEKLY_ID, "ok")]
        assert rows("SELECT delivery_id, status FROM deliveries ORDER BY as_of") == [(LAUNCH_ID, "loaded"), (FIRST_WEEKLY_ID, "loaded")]
        assert seal_path.read_bytes() == launch_seal, "the seal is the launch's: the second run did not touch it"
        assert [row for row in rows(registry) if row[0] == launch_models[0][0]] == launch_models, "the models of the launch round are the registered ones"
        delivered = rows("SELECT round_id, SUM(contacts), COUNT(*) FROM crm_deliveries WHERE status = 'ok' AND readback_equal = 1 GROUP BY round_id ORDER BY round_id")
        assert [r[0] for r in delivered] == ["R2011-03-28", "R2011-04-04"] and all(r[1] > 0 for r in delivered), "each run delivered the lists of its round"
        held = crm_rows("SELECT round_id, COUNT(*), COUNT(DISTINCT contact_id) FROM lists GROUP BY round_id ORDER BY round_id")
        issued = rows("SELECT round_id, delivered FROM round_ops ORDER BY round_id")
        assert [(r, n) for r, n, _d in held] == issued and all(n == d for _r, n, d in held), "the CRM holds each list once, as many as the round says it delivered"
        assert (QUICK / "outputs" / "site" / "manifest.json").is_file() and (QUICK / "dashboard" / "powerbi-design.html").is_file()
    finally:
        problems = teardown(existing, existing_mounts, image_existed=image_existed, external_existed=external_existed)
        left = leftovers()
        if any(left.values()):
            problems.append(f"the compose project still owns {left}")
        if not image_existed and image_exists(IMAGE):
            problems.append(f"{IMAGE} is still there")
        if problems:
            sys.stderr.write("TEARDOWN FAILED:\n" + "\n".join(problems) + "\n")
    assert not problems, "the teardown failed, so the next run will find leftovers:\n" + "\n".join(problems)

