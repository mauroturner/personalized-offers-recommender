"""The Airflow compose file, its image and its initialization (U20, AC35; D26): nothing exposed beyond the machine, every secret from the environment with ``${VAR:?}`` and no value (the password of the
metadata database included, in the PostgreSQL service and in the connection string), read-only code and source data, the same pins as the command line, external images pinned by version and digest,
a project name of its own, an initialization that stops at its first failure and one more service of the same image on the internal network (the stand-in of the CRM) that holds only its own
secret. Adapted from project 07's ``tests/unit/test_compose.py``; static: nothing is built or started (the Docker test, ``tests/e2e/test_airflow_docker.py``, has the ``docker`` mark)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
SECRETS = ("PERSONALOFFERS_DB_PASSWORD", "PERSONALOFFERS_FERNET_KEY", "PERSONALOFFERS_JWT_SECRET", "PERSONALOFFERS_ADMIN_PASSWORD", "PERSONALOFFERS_CRM_TOKEN")
REQUIRED = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*):\?(?P<message>[^}]*)\}")   # ${NAME:?message}: the file refuses to start without NAME
SECRET_NAME = re.compile(r"PASSWORD|SECRET|KEY|TOKEN", re.IGNORECASE)
# scheme://user:password@host; the password is a whole ${...} interpolation (whose message may have spaces and slashes) or a run of characters a URL allows
USERINFO = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?P<user>[^:/@\s]*):(?P<password>\$\{[^}]*\}|[^@/\s]+)@")


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def service(text: str, name: str) -> str:
    """The lines of one service of the compose file, from its key to the next service (or the end of ``services``)."""
    found = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z][\w-]*:\s*$|^\S)", text, flags=re.MULTILINE | re.DOTALL)
    assert found, f"no service {name}"
    return found.group(1)


def values_of(text: str) -> list[tuple[str, str]]:
    """Every value of the file with the key that holds it: ``key: value`` pairs, ``- KEY=value`` and ``- value`` list items, line by line."""
    found: list[tuple[str, str]] = []
    for line in code_lines(text):
        body = line.strip()
        item = re.match(r"-\s+(?P<value>.+)$", body)
        if item:
            body = item.group("value")
            pair = re.match(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$", body)
            found.append((pair.group("key"), pair.group("value")) if pair else ("", body))
            continue
        pair = re.match(r"(?P<key>[A-Za-z_<][A-Za-z0-9_<>*-]*):\s*(?P<value>.*)$", body)
        if pair and pair.group("value"):
            found.append((pair.group("key"), pair.group("value").strip().strip("'\"")))
        else:
            found.append(("", body))
    return found


def find_literal_secrets(text: str) -> list[str]:
    """What in the file is a secret with a value: the value of a key that looks like a secret that is not ``${NAME:?...}``, a password inside a
    connection string that is not ``${NAME:?...}``, and a ``${NAME}`` or ``${NAME:-default}`` of a secret (a default is a literal)."""
    problems = []
    for key, value in values_of(text):
        if key and SECRET_NAME.search(key) and value and not REQUIRED.fullmatch(value):
            problems.append(f"{key}: a secret key with the value {value!r}")
        for match in USERINFO.finditer(value):
            if not REQUIRED.fullmatch(match.group("password")):
                problems.append(f"{key or 'value'}: a password in a connection string, {match.group('password')!r}")
    for name in SECRETS:
        for use in re.findall(r"\$\{" + re.escape(name) + r"(?!:\?)[^}]*\}", text):
            problems.append(f"{name}: used without ':?' in {use}")
    return problems


@pytest.fixture(scope="module")
def compose() -> str:
    return (AIRFLOW / "docker-compose.yaml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (AIRFLOW / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def init_script() -> str:
    return (AIRFLOW / "init.sh").read_bytes().decode("utf-8")   # the bytes: read_text would turn a CRLF into LF and hide the carriage returns the test looks for


# --- the RED of U21 ---------------------------------------------------------------------------------------------------------------------


def test_no_literal_secret_including_the_metadata_db_password(compose):
    """AC33 (project 02, A6 and its D68): every value of the compose file is read and no secret has one. The password of the metadata
    database comes from the environment in the PostgreSQL service and inside the connection string of the Airflow services."""
    assert find_literal_secrets(compose) == []
    values = values_of(compose)
    assert len(values) > 80, "the walk reads the whole file, not a few lines"
    database = [(k, v) for k, v in values if "PERSONALOFFERS_DB_PASSWORD" in v]
    assert {k for k, _ in database} == {"POSTGRES_PASSWORD", "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"}
    [connection] = [v for k, v in database if k == "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"]
    assert re.fullmatch(r"postgresql\+psycopg://airflow:\$\{PERSONALOFFERS_DB_PASSWORD:\?[^}]+\}@postgres/airflow", connection)
    assert not re.search(r"airflow:airflow@|POSTGRES_PASSWORD:\s*airflow\b", compose), "the literal of the official file is gone"
    for name in SECRETS:
        uses = [line for line in code_lines(compose) if "${" + name in line]
        assert uses and all("${" + name + ":?" in line for line in uses), name


def test_the_init_script_stops_at_the_first_failure(init_script):
    """The other services start only when the init exits 0 (``service_completed_successfully``); without ``set -e`` a failed migration in
    ``/entrypoint`` is followed by a ``chown`` that succeeds and the init reports success (project 03, review of U23)."""
    commands = code_lines(init_script)
    assert commands[0] == "set -euo pipefail", commands[:2]
    assert "\r" not in init_script, "the script is read by bash in a Linux container: no carriage returns"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash to run the init script")
def test_a_failed_migration_makes_the_init_exit_non_zero(init_script, tmp_path):
    """The script with ``/entrypoint`` replaced by a command that fails, as a failed ``airflow db migrate`` does, and ``chown`` by one that succeeds."""
    stub = 'failed_migration() { echo "migration failed" >&2; return 3; }\n'
    script = init_script.replace("/opt/airflow", "./airflow").replace("/entrypoint", "failed_migration").replace("chown ", "true ")
    done = subprocess.run(["bash", "-c", stub + script], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert done.returncode == 3, done.stdout + done.stderr
    assert done.stderr.count("migration failed") == 1, "the second /entrypoint call never runs"
    assert (tmp_path / "airflow" / "logs").is_dir(), "the commands before the failure did run"


# --- the walk is not vacuous ----------------------------------------------------------------------------------------------------------


def secret_of(compose: str, name: str) -> str:
    [found] = set(re.findall(r"\$\{" + re.escape(name) + r":\?[^}]*\}", compose))
    return found


@pytest.mark.parametrize(("name", "replacement"), [
    ("PERSONALOFFERS_DB_PASSWORD", "airflow"), ("PERSONALOFFERS_DB_PASSWORD", "${PERSONALOFFERS_DB_PASSWORD:-airflow}"), ("PERSONALOFFERS_DB_PASSWORD", "${PERSONALOFFERS_DB_PASSWORD}"),
    ("PERSONALOFFERS_FERNET_KEY", "0123456789abcdef"), ("PERSONALOFFERS_JWT_SECRET", "secret"), ("PERSONALOFFERS_ADMIN_PASSWORD", "airflow"),
])
def test_the_walk_finds_a_secret_that_gets_a_value_or_a_default(compose, name, replacement):
    """Each way a secret could get a value (a literal, a default, no ``:?``) is found, in every place the secret is used."""
    required = secret_of(compose, name)
    places = compose.count(required)
    assert places >= 1
    for i in range(places):   # one place at a time: a literal in only one of the uses is found too
        parts = compose.split(required)
        mutated = required.join(parts[: i + 1]) + replacement + required.join(parts[i + 1:])
        assert find_literal_secrets(mutated), (name, replacement, i)


@pytest.mark.parametrize("literal", ["hunter2", "${PERSONALOFFERS_DB_PASSWORD:-airflow}", "${PERSONALOFFERS_DB_PASSWORD}x", "pa%2Fss"])
def test_a_literal_password_in_the_real_connection_string_is_found(compose, literal):
    [connection] = [v for k, v in values_of(compose) if k == "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"]
    [match] = list(USERINFO.finditer(connection))
    assert match.group("user") == "airflow" and REQUIRED.fullmatch(match.group("password")) and " " in match.group("password")
    mutated = compose.replace(f"airflow:{match.group('password')}@postgres", f"airflow:{literal}@postgres", 1)
    assert mutated != compose and find_literal_secrets(mutated), literal


# --- the rest of AC33 --------------------------------------------------------------------------------------------------------------------


def test_the_interface_is_published_on_localhost_only_and_nothing_else_publishes_a_port(compose):
    published = re.findall(r'^\s*-\s*"?(\d[\d.]*:\d+:\d+|\d+:\d+)"?\s*$', "\n".join(code_lines(compose)), flags=re.MULTILINE)
    assert published == ["127.0.0.1:8080:8080"]
    for name in ("postgres", "crm"):
        assert not re.search(r"^\s*(ports|expose|network_mode):", service(compose, name), flags=re.MULTILINE), f"{name} is reached on the internal network of the compose project only"
    assert len(re.findall(r"^\s*ports:\s*$", compose, flags=re.MULTILINE)) == 1


def test_the_example_environment_lists_the_five_secrets_empty(compose):
    """``.env.example`` is a template: the five names, each empty, and comments that say how to generate each; nothing else has a value."""
    example = (AIRFLOW / ".env.example").read_text(encoding="utf-8")
    assert [line.strip() for line in code_lines(example)] == [f"{name}=" for name in SECRETS]
    comments = " ".join(line for line in example.splitlines() if line.lstrip().startswith("#"))
    assert "secrets.token_hex" in comments and "urlsafe_b64encode" in comments and "token_urlsafe" in comments


def mounts_of(text: str) -> list[str]:
    return [line.split("-", 1)[1].strip() for line in code_lines(text) if re.match(r"\s*-\s*\.\.[:/]", line)]


def test_the_code_and_the_configuration_are_mounted_read_only_and_only_the_data_and_outputs_are_writable(compose):
    common = re.search(r"^x-airflow-common:\n(.*?)^services:", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    for text in (common, service(compose, "crm")):
        mounts = mounts_of(text)
        assert not [m for m in mounts if m.split(":")[0] in ("..", "../")], "the whole project, writable, is not mounted"
        read_only = {m.split(":")[0] for m in mounts if m.endswith(":ro")}
        writable = {m.split(":")[0] for m in mounts if not m.endswith(":ro")}
        assert read_only == {"../src", "../sql", "../config", "../data/raw"}, "the UCI zip is the owner's: no task writes it"
        assert writable == {"../data", "../outputs", "../reports", "../dashboard"}
        assert all(m.split(":")[1].startswith("/opt/personaloffers/") for m in mounts)
    local = [line.split("-", 1)[1].strip() for line in code_lines(common) if re.match(r"\s*-\s*\./", line)]
    assert {"./dags:/opt/airflow/dags:ro", "./plugins:/opt/airflow/plugins:ro", "./init.sh:/opt/airflow/init.sh:ro"} <= set(local)
    assert {m.split(":")[0] for m in local if not m.endswith(":ro")} == {"./logs", "./config"}, "only what Airflow itself writes"


def test_the_pipeline_finds_its_code_and_its_configuration_inside_the_container(compose):
    text = "\n".join(code_lines(compose))
    for fragment in ("AIRFLOW__CORE__EXECUTOR: LocalExecutor", "AIRFLOW__CORE__LOAD_EXAMPLES: 'false'", "image: personaloffers-airflow:3.4.0"):
        assert fragment in text, fragment
    common = re.search(r"^x-airflow-common:\n(.*?)^services:", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    for where, block in (("the Airflow services", common), ("crm", service(compose, "crm"))):
        for fragment in ("PYTHONPATH: /opt/personaloffers/src", "PERSONALOFFERS_HOME: /opt/personaloffers", "PERSONALOFFERS_CONFIG: ${PERSONALOFFERS_CONFIG:-/opt/personaloffers/config/pipeline.docker.toml}"):
            assert fragment in block, (where, fragment)
    for other in ("promolift", "flotsilica", "churnrisk", "oilgas", "custseg", "latedel"):
        assert other not in text.lower(), f"no name of another project: {other}"
    assert re.search(r"^name: personaloffers-airflow$", compose, flags=re.MULTILINE), "its own volume and network"


def test_the_external_images_are_pinned_by_version_and_by_digest(compose, dockerfile):
    external = re.findall(r"^\s*image:\s*(postgres\S+)\s*$", compose, flags=re.MULTILINE) + re.findall(r"^FROM\s+(\S+)", dockerfile, flags=re.MULTILINE)
    assert len(external) == 2
    for image in external:
        assert re.fullmatch(r"[a-z/]+:\d+(\.\d+)+@sha256:[0-9a-f]{64}", image), image
    assert external[1] == "apache/airflow:3.4.0@sha256:a8d9d19c563c768b2bc605ef26440f28a9164ea886064e99c599b057432ff572", "the digest projects 04 to 07 pinned (D26)"
    assert external[0] == "postgres:16.9@sha256:ddfe3e8713e3ee5b8f286082cb12512488dfbf3f5a1ecb0b74a42e6055af0a5f", "the PostgreSQL that projects 04 to 07 pinned"
    ours = re.findall(r"^\s*image:\s*(personaloffers\S+)\s*$", compose, flags=re.MULTILINE)
    assert ours and set(ours) == {"personaloffers-airflow:3.4.0"}, "the Airflow services and the CRM stand-in run one image"


def test_the_image_installs_the_exact_pins_of_the_command_line_from_a_context_of_the_requirements_only(compose, dockerfile):
    assert "COPY requirements.txt /" in dockerfile
    assert 'RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt' in dockerfile
    assert re.search(r"^ARG AIRFLOW_VERSION=3\.4\.0$", dockerfile, flags=re.MULTILINE)
    pins = [line for line in code_lines((PROJECT / "requirements.txt").read_text(encoding="utf-8")) if not line.startswith("-r ")]
    assert pins and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][^\s]*", line) for line in pins), "every requirement is pinned with =="
    assert "implicit==0.7.3" in pins, "ALS: the wheel of this version for the image is what the build of the Docker test checks"
    assert code_lines((PROJECT / ".dockerignore").read_text(encoding="utf-8")) == ["*", "!requirements*.txt", "!src/", "!sql/", "!config/", "**/__pycache__/", "**/*.pyc"]
    assert len(re.findall(r"^\s*build:\s*$", compose, flags=re.MULTILINE)) == 1, "only the init builds: five builds of one tag race on a cold cache"
    init = service(compose, "airflow-init")
    assert re.search(r"build:\s*\n\s*context:\s*\.\.\s*\n\s*dockerfile:\s*airflow/Dockerfile", init)


def test_the_init_service_runs_the_script_and_the_others_wait_for_it(compose, init_script):
    init = re.search(r"^  airflow-init:\n(.*?)^  # ", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    assert "/opt/airflow/init.sh" in init and "entrypoint: /bin/bash" in init
    assert len(re.findall(r"condition: service_completed_successfully", compose)) == 4
    [chown] = [line for line in code_lines(init_script) if "chown" in line]
    assert "logs" in chown and "config" in chown and "dags" not in chown and "plugins" not in chown, "a read-only mount cannot be chowned"


def test_the_debug_service_says_it_runs_outside_the_guard_of_one_active_run(compose):
    """``airflow dags test`` in the debug service runs outside the scheduler's ``max_active_runs=1``: a second writer of the warehouse is
    possible, and the compose file says so (project 03, D80 and D82; plan, section 22)."""
    lines = compose.splitlines()
    [start] = [i for i, line in enumerate(lines) if line == "  airflow-cli:"]
    top = start
    while lines[top - 1].startswith("  #"):
        top -= 1
    comment = " ".join(line.strip().lstrip("#").strip() for line in lines[top:start])
    for needle in ("max_active_runs", "SQLite", "docker compose stop airflow-scheduler", "runbook", "pipeline.lock", "between two tasks"):
        assert needle in comment, needle


def test_the_compose_file_says_how_to_set_airflow_uid(compose):
    common = re.search(r"^x-airflow-common:\n(.*?)^services:", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    assert 'user: "${AIRFLOW_UID:-50000}:0"' in common
    comments = " ".join(line.strip() for line in common.splitlines() if line.strip().startswith("#"))
    assert "AIRFLOW_UID" in comments and "id -u" in comments and "Linux" in comments


def test_the_docker_test_removes_the_image_it_built_and_keeps_one_it_found(compose, monkeypatch, tmp_path):
    """A13 of project 04's evaluation (D24): its Docker test left its image behind. The teardown of this project's removes the image when the
    test built it, and keeps it when it was already there before the test; the name is the compose file's. No Docker command runs here: the
    teardown's ``docker`` calls are recorded, and its folders point inside ``tmp_path``."""
    from tests.e2e import test_airflow_docker as docker_test

    calls: list[tuple[str, ...]] = []

    def recorded(*args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(["docker", *args], 0, "", "")

    monkeypatch.setattr(docker_test, "docker", recorded)
    for name, folder in (("PROJECT", tmp_path), ("AIRFLOW", tmp_path / "airflow"), ("QUICK", tmp_path / "data" / "quick")):
        monkeypatch.setattr(docker_test, name, folder)
    assert f"image: {docker_test.IMAGE}" in compose
    assert docker_test.teardown(set(docker_test.CREATED), set(docker_test.MOUNTED), image_existed=False) == []
    assert calls == [docker_test.DOWN, ("image", "rm", docker_test.IMAGE), *[("image", "rm", ref) for ref in docker_test.EXTERNAL]], "the built image goes before its bases"
    calls.clear()
    assert docker_test.teardown(set(docker_test.CREATED), set(docker_test.MOUNTED), image_existed=True, external_existed=docker_test.EXTERNAL) == []
    assert calls == [docker_test.DOWN], "images that were there before the test stay"
    calls.clear()
    assert docker_test.teardown(set(), set(), image_existed=True, external_existed=docker_test.EXTERNAL[:1]) == []
    assert calls == [docker_test.DOWN, ("image", "rm", docker_test.EXTERNAL[1])], "only the base this test pulled goes"


def test_the_docker_test_removes_the_folders_it_created_and_only_those(monkeypatch, tmp_path):
    """The mounts create ``data/raw``, ``outputs``, ``reports`` and ``dashboard`` when they are missing, the containers ``airflow/logs``, ``config`` and
    ``plugins``: the teardown removes those that did not exist before the test (and ``data/quick``), and a folder with content it did not put there stays and is
    reported."""
    from tests.e2e import test_airflow_docker as docker_test

    monkeypatch.setattr(docker_test, "docker", lambda *args, **_kwargs: subprocess.CompletedProcess(["docker", *args], 0, "", ""))
    for name, folder in (("PROJECT", tmp_path), ("AIRFLOW", tmp_path / "airflow"), ("QUICK", tmp_path / "data" / "quick")):
        monkeypatch.setattr(docker_test, name, folder)
    for name in ("data/raw", "data/quick", "outputs", "reports", "dashboard", "airflow/logs", "airflow/config", "airflow/plugins"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "data" / "raw" / "kept.parquet").write_text("owner's file", encoding="utf-8")
    (tmp_path / "airflow" / "plugins" / "kept.py").write_text("x", encoding="utf-8")
    problems = docker_test.teardown({"plugins"}, {"data", "reports"}, image_existed=True, external_existed=docker_test.EXTERNAL)
    assert [p for p in problems if "data/raw" in p.replace("\\", "/")] and len(problems) == 1, problems   # created by the mounts but not empty: kept and reported
    assert (tmp_path / "data" / "raw" / "kept.parquet").is_file() and (tmp_path / "data").is_dir()
    assert not (tmp_path / "data" / "quick").exists() and not (tmp_path / "outputs").exists() and not (tmp_path / "dashboard").exists()
    assert (tmp_path / "reports").is_dir() and (tmp_path / "airflow" / "plugins" / "kept.py").is_file(), "what was there before stays"
    assert not (tmp_path / "airflow" / "logs").exists() and not (tmp_path / "airflow" / "config").exists()


# --- what this project keeps from the compose of project 05 ----------------------------------------------------------------------------------------------


def test_the_file_with_the_real_secrets_is_never_versioned_and_the_example_is(compose):
    """``airflow/.env`` holds the owner's six secrets: ``.gitignore`` names it (and what Airflow writes beside it), and ``.env.example`` (the empty template) is not matched by any pattern."""
    patterns = [line.strip() for line in code_lines((PROJECT / ".gitignore").read_text(encoding="utf-8"))]
    assert {"airflow/.env", "airflow/logs/", "airflow/config/", "airflow/plugins/"} <= set(patterns)
    assert "docker/.env" not in patterns, "the n8n plan's entry is gone (D26)"
    assert not [p for p in patterns if p in ("*", ".env*", "airflow/.env*", "airflow/*", "airflow/")], "a broad pattern would hide .env.example too"
    assert "env_file" not in "\n".join(code_lines(compose)), "compose fills the variables from airflow/.env; no container gets the whole file, so each one holds only the secrets its service names"


def test_the_image_and_the_script_hold_no_secret_and_the_image_ends_as_the_user_of_airflow(dockerfile, init_script):
    """No ``ARG``/``ENV`` of a secret in the image (it would stay in its layers), none in the script; ``root`` is only the user of the one ``apt-get`` and the image ends as ``airflow``."""
    for text in (dockerfile, init_script):
        assert not SECRET_NAME.search("\n".join(line for line in code_lines(text) if re.match(r"(ARG|ENV)\s", line))), text[:60]
        assert not re.search(r"(?i)(password|secret|token|fernet)\w*\s*=\s*[\"']?[A-Za-z0-9+/=_-]{8,}", "\n".join(code_lines(text)))
    users = re.findall(r"^USER\s+(\S+)", dockerfile, flags=re.MULTILINE)
    assert users == ["root", "airflow"], users
    assert dockerfile.index("apt-get install") < dockerfile.index("USER airflow") < dockerfile.index("pip install"), "pip runs as airflow, apt as root"
    assert re.search(r"apt-get install --no-install-recommends -y libgomp1=\d+(\.\d+)+-\d+\S*\s", dockerfile), "the OpenMP runtime that implicit loads (the Docker test found it missing), with its version"
    assert "torch" not in dockerfile and "libzbar" not in dockerfile, "nothing of project 07's image"
    assert not re.search(r"^EXPOSE", dockerfile, flags=re.MULTILINE), "the base image's ports stay"
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_the_pipeline_reads_the_quick_or_the_full_configuration_by_the_environment_and_nothing_names_a_default_secret(compose):
    """``PERSONALOFFERS_CONFIG`` is the only optional setting that reaches the pipeline, and it is a path, not a secret."""
    optional = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-", compose))
    assert optional == {"AIRFLOW__API_AUTH__JWT_ISSUER", "PERSONALOFFERS_CONFIG", "AIRFLOW_UID", "_AIRFLOW_WWW_USER_USERNAME"}
    assert not [name for name in optional if SECRET_NAME.search(name) and name != "AIRFLOW__API_AUTH__JWT_ISSUER"], "no secret has a default"


# --- the CRM stand-in, the one service of the pipeline ---------------------------------------------------------------------------------------------------


def flat(text: str) -> str:
    """The text of a block on one line with single spaces: a YAML list is then ``- a - b - c``, and a pattern need not know where its lines break."""
    return " ".join(text.split())


def test_the_crm_runs_uvicorn_with_its_factory_and_holds_only_its_own_secret(compose):
    """The stand-in is the only writer of ``data/crm/standin.sqlite`` in Docker and listens on the internal network of the project (the only place ``0.0.0.0`` is allowed: ``serve-crm`` refuses it) with the
    token it needs and no other secret: not the database, the Fernet key, the JWT secret or the administrator's password. There is no entry API (D27)."""
    crm = service(compose, "crm")
    factory = "personaloffers.crm.standin:create_app_from_environment"
    assert f'command: - python - -m - uvicorn - --factory - {factory} - --host - 0.0.0.0 - --port - "8001"' in flat(crm)
    assert "image: personaloffers-airflow:3.4.0" in crm and "env_file" not in crm, "no file of secrets: the environment names each"
    assert "PYTHONPATH: /opt/personaloffers/src" in crm and "PERSONALOFFERS_HOME: /opt/personaloffers" in crm and "restart:" in crm and "profiles" not in crm, "the stand-in is part of the stack"
    for name in ("PERSONALOFFERS_DB_PASSWORD", "PERSONALOFFERS_FERNET_KEY", "PERSONALOFFERS_JWT_SECRET", "PERSONALOFFERS_ADMIN_PASSWORD"):
        assert name not in crm, name
    assert "PERSONALOFFERS_CRM_TOKEN: ${PERSONALOFFERS_CRM_TOKEN:?" in crm
    common = re.search(r"^x-airflow-common:\n(.*?)^services:", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    assert "PERSONALOFFERS_CRM_TOKEN: ${PERSONALOFFERS_CRM_TOKEN:?" in common, "the DAG sends the token of the CRM"
    assert not re.search(r"^  api:", compose, flags=re.MULTILINE) and "API_TOKEN" not in compose.replace("AIRFLOW__API_AUTH", ""), "the project has no entry API (D27)"


def test_the_configuration_of_the_compose_project_points_the_dag_at_the_crm_service_and_changes_nothing_else():
    """``config/pipeline.docker.toml`` is the pipeline's configuration with the CRM at the ``crm`` service of the compose file (D26): only ``[crm]`` changes, and it is not sealed, so the seal and every figure are
    those of the configuration of the command line."""
    import dataclasses

    from personaloffers.config import UNSEALED_KEYS, load_config

    docker = load_config(PROJECT / "config" / "pipeline.docker.toml")
    plain = load_config(PROJECT / "config" / "pipeline.toml")
    assert (docker.crm.mode, docker.crm.base_url) == ("http", "http://crm:8001") and plain.crm.mode == "standin"
    assert dataclasses.replace(docker, crm=plain.crm) == plain
    assert {"crm.mode", "crm.base_url"} <= set(UNSEALED_KEYS)
    crm = service((AIRFLOW / "docker-compose.yaml").read_text(encoding="utf-8"), "crm")
    assert '- --port - "8001"' in flat(crm), "the port of the stand-in is the one the configuration names"
