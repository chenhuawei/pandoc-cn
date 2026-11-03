FROM pandoc-md2docx:local

COPY requirements-mcp.txt /tmp/requirements-mcp.txt
RUN /opt/md2docx-venv/bin/pip install --no-cache-dir \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements-mcp.txt

ENTRYPOINT ["/opt/md2docx-venv/bin/python", "/opt/md2docx/mcp_server.py"]
