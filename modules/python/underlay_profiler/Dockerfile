# Build from telescope/modules/python:
#   docker build -f underlay_profiler/Dockerfile -t <registry>/underlay-profiler:<tag> .
ARG BASE_IMAGE=mcr.microsoft.com/azurelinux/base/python:3.12.14-2-azl3.0.20260923
FROM ${BASE_IMAGE}

WORKDIR /app
COPY underlay_profiler/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Only the pure-Python pieces the collector shares with the load-test harness
# (not the harness itself): decoder, category rules, roll-up, schema, quantity parsing.
COPY vmagent_loadtest/__init__.py vmagent_loadtest/config.py vmagent_loadtest/pprof.py \
     vmagent_loadtest/categories.py vmagent_loadtest/quantity.py vmagent_loadtest/rollup.py \
     vmagent_loadtest/profile_schema.py vmagent_loadtest/
COPY underlay_profiler underlay_profiler

USER 65532:65532
ENTRYPOINT ["python3", "-m", "underlay_profiler"]
CMD ["--config", "/etc/profiler/config.yaml"]
