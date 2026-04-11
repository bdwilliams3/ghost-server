from mcp.server.fastmcp import FastMCP
from kubernetes import client, config

mcp = FastMCP("ghost-cluster", host="0.0.0.0", port=8000)

config.load_incluster_config()
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()

@mcp.tool()
def list_pods(namespace: str = "") -> str:
    if namespace:
        pods = v1.list_namespaced_pod(namespace)
    else:
        pods = v1.list_pod_for_all_namespaces()
    return "\n".join([f"{p.metadata.namespace}/{p.metadata.name} - {p.status.phase}" for p in pods.items])

@mcp.tool()
def get_logs(namespace: str, pod: str) -> str:
    return v1.read_namespaced_pod_log(name=pod, namespace=namespace, tail_lines=50)

@mcp.tool()
def list_services(namespace: str = "") -> str:
    if namespace:
        svcs = v1.list_namespaced_service(namespace)
    else:
        svcs = v1.list_service_for_all_namespaces()
    return "\n".join([f"{s.metadata.namespace}/{s.metadata.name}" for s in svcs.items])

@mcp.tool()
def list_deployments(namespace: str = "") -> str:
    if namespace:
        deps = apps_v1.list_namespaced_deployment(namespace)
    else:
        deps = apps_v1.list_deployment_for_all_namespaces()
    return "\n".join([f"{d.metadata.namespace}/{d.metadata.name} - ready: {d.status.ready_replicas}/{d.spec.replicas}" for d in deps.items])

@mcp.tool()
def get_events(namespace: str = "") -> str:
    if namespace:
        evts = v1.list_namespaced_event(namespace)
    else:
        evts = v1.list_event_for_all_namespaces()
    return "\n".join([f"{e.metadata.namespace} - {e.reason}: {e.message}" for e in evts.items])

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
