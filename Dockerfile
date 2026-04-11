FROM python:3.12-slim
WORKDIR /app
RUN pip install fastmcp kubernetes
COPY mcp_server.py .
CMD ["python", "mcp_server.py"]
