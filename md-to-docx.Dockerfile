ARG BASE_IMAGE=pandoc-cn:local
FROM ${BASE_IMAGE}

ENV SOFFICE=/usr/bin/soffice \
    PANDOC_DEFAULTS_FILE=/usr/local/share/pandoc/defaults/pandoc-cn-diagrams.yaml \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    libreoffice-writer \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements-md-to-docx.txt /tmp/requirements-md-to-docx.txt
RUN python3 -m venv /opt/md2docx-venv \
    && /opt/md2docx-venv/bin/pip install --no-cache-dir \
       --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
       -r /tmp/requirements-md-to-docx.txt

COPY md2docx /opt/md2docx

WORKDIR /work
ENTRYPOINT ["/opt/md2docx-venv/bin/python", "/opt/md2docx/scripts/convert.py"]
