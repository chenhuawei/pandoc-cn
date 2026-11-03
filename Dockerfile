FROM ubuntu:24.04

ARG DRAWIO_VERSION=30.0.4
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PUPPETEER_CACHE_DIR=/usr/local/share/puppeteer \
    SOFFICE=/usr/bin/soffice \
    PANDOC_DEFAULTS_FILE=/usr/local/share/pandoc/defaults/pandoc-cn-diagrams.yaml \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    pandoc \
    default-jre-headless \
    graphviz \
    curl \
    nodejs \
    npm \
    xvfb \
    libasound2t64 \
    libatk-bridge2.0-0t64 \
    libatk1.0-0t64 \
    libcairo2 \
    libcups2t64 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0t64 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxkbcommon0 \
    libxrandr2 \
    libxshmfence1 \
    libxss1 \
    libxtst6 \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-noto-mono \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y \
    texlive-xetex \
    texlive-lang-chinese \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-science \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -fL --retry 5 --retry-all-errors --connect-timeout 20 \
    -o /tmp/drawio.deb \
    "https://github.com/jgraph/drawio-desktop/releases/download/v${DRAWIO_VERSION}/drawio-${TARGETARCH}-${DRAWIO_VERSION}.deb" \
    && apt-get update \
    && apt-get install -y /tmp/drawio.deb \
    && rm -f /tmp/drawio.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN PUPPETEER_SKIP_DOWNLOAD=true npm install -g \
    @mermaid-js/mermaid-cli@11.12.0 \
    playwright@1.49.1 \
    && PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright playwright install chromium \
    && chromium_path=$(find /usr/local/share/playwright -type f -path '*/chrome-linux*/chrome' | head -n 1) \
    && test -n "$chromium_path" \
    && ln -s "$chromium_path" /usr/local/bin/chromium \
    && chmod -R a+rX /usr/local/share/playwright

RUN curl -fL --retry 5 --retry-all-errors --connect-timeout 20 \
    -o /usr/local/bin/plantuml.jar \
    "https://github.com/plantuml/plantuml/releases/download/v1.2026.2/plantuml-1.2026.2.jar" \
    && printf '#!/bin/bash\nexec java -jar /usr/local/bin/plantuml.jar "$@"\n' > /usr/local/bin/plantuml \
    && chmod +x /usr/local/bin/plantuml

RUN mkdir -p /usr/local/share/pandoc/filters /usr/local/share/pandoc/defaults

COPY plantuml-filter.lua /usr/local/share/pandoc/filters/plantuml-filter.lua
COPY diagram-image-filter.lua /usr/local/share/pandoc/filters/diagram-image-filter.lua
COPY puppeteer-config.json /usr/local/share/pandoc/filters/puppeteer-config.json
COPY pandoc-cn-diagrams.yaml /usr/local/share/pandoc/defaults/pandoc-cn-diagrams.yaml

RUN fc-cache -fv

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    libreoffice-writer \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements-md-to-docx.txt /tmp/requirements-md-to-docx.txt
RUN python3 -m venv /opt/md2docx-venv \
    && /opt/md2docx-venv/bin/pip install --no-cache-dir \
    -r /tmp/requirements-md-to-docx.txt

COPY md2docx /opt/md2docx

WORKDIR /work
ENTRYPOINT ["/opt/md2docx-venv/bin/python", "/opt/md2docx/scripts/convert.py"]
