FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV PUPPETEER_CACHE_DIR=/usr/local/share/puppeteer

ARG DRAWIO_VERSION=30.0.4
ARG TARGETARCH

RUN sed -i \
    -e 's|http://archive.ubuntu.com/ubuntu/|http://mirror.sjtu.edu.cn/ubuntu/|g' \
    -e 's|http://security.ubuntu.com/ubuntu/|http://mirror.sjtu.edu.cn/ubuntu/|g' \
    -e 's|http://ports.ubuntu.com/ubuntu-ports/|http://mirror.sjtu.edu.cn/ubuntu-ports/|g' \
    /etc/apt/sources.list.d/ubuntu.sources \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/99retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://mirror.sjtu.edu.cn|https://mirror.sjtu.edu.cn|g' \
       /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install base tools, fonts, and headless browser/runtime dependencies
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
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
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

# Install texlive
RUN apt-get update && apt-get install -y \
    texlive-xetex \
    texlive-lang-chinese \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-science \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install draw.io Desktop for command-line diagram export
RUN curl -L -o /tmp/drawio.deb \
    "https://github.com/jgraph/drawio-desktop/releases/download/v${DRAWIO_VERSION}/drawio-${TARGETARCH}-${DRAWIO_VERSION}.deb" \
    && apt-get update \
    && apt-get install -y /tmp/drawio.deb \
    && rm -f /tmp/drawio.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Mermaid CLI and an ARM64 Chromium for Puppeteer
RUN PUPPETEER_SKIP_DOWNLOAD=true npm install -g \
    @mermaid-js/mermaid-cli@11.12.0 \
    playwright@1.49.1 \
    && PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright playwright install chromium \
    && chromium_path=$(find /usr/local/share/playwright -type f -path '*/chrome-linux*/chrome' | head -n 1) \
    && test -n "$chromium_path" \
    && ln -s "$chromium_path" /usr/local/bin/chromium \
    && chmod -R a+rX /usr/local/share/playwright

# Install PlantUML
RUN curl -fL --retry 3 --retry-all-errors --connect-timeout 20 \
    -o /usr/local/bin/plantuml.jar \
    "https://maven.aliyun.com/repository/central/net/sourceforge/plantuml/plantuml/1.2026.2/plantuml-1.2026.2.jar" \
    && printf '#!/bin/bash\nexec java -jar /usr/local/bin/plantuml.jar "$@"\n' > /usr/local/bin/plantuml \
    && chmod +x /usr/local/bin/plantuml

RUN mkdir -p /usr/local/share/pandoc/filters /usr/local/share/pandoc/defaults

# Embed PlantUML lua filter for Pandoc
COPY plantuml-filter.lua /usr/local/share/pandoc/filters/plantuml-filter.lua
COPY diagram-image-filter.lua /usr/local/share/pandoc/filters/diagram-image-filter.lua
COPY puppeteer-config.json /usr/local/share/pandoc/filters/puppeteer-config.json
COPY pandoc-cn-diagrams.yaml /usr/local/share/pandoc/defaults/pandoc-cn-diagrams.yaml

# Refresh font cache
RUN fc-cache -fv

WORKDIR /docs
ENTRYPOINT ["pandoc"]
