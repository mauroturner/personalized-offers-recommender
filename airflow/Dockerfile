# Airflow with the libraries of the pipeline, at the exact versions of requirements.txt (the same == pins as the command line, RNF01, D35). The official pattern: reinstall apache-airflow at the
# same version so that pip never changes it while it resolves the other packages; if a pin ever conflicts with Airflow's own constraints the build fails instead of installing another version.
# The build context is the project folder (see docker-compose.yaml), and .dockerignore lets only the requirements files, src/, sql/ and config/ into it (src/, sql/ and config/ are mounted over
# /opt/personaloffers at run time).
# The base image is pinned by its version and by its digest, the one projects 04 to 07 pinned (D26): the tag alone can be moved to other bytes.
# implicit 0.7.3 (ALS) is installed from its wheel for the image's Linux and Python, with no compiler in the image: if the wheel were missing, pip would try to build it and the build would fail
# (U20 checks it with the build of the Docker test, and ``pip check`` judged by its exit code).
FROM apache/airflow:3.4.0@sha256:a8d9d19c563c768b2bc605ef26440f28a9164ea886064e99c599b057432ff572

ARG AIRFLOW_VERSION=3.4.0

# The OpenMP runtime that implicit's compiled module loads (libgomp.so.1): the base image does not have it, and without it ``import implicit`` fails (the Docker test found it). Its version is pinned.
USER root
RUN apt-get update     && apt-get install --no-install-recommends -y libgomp1=14.2.0-19+deb13u0+dhi8     && apt-get clean     && rm -rf /var/lib/apt/lists/*
USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt
