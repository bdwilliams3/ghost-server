from mcp.server.fastmcp import FastMCP
from kubernetes import client, config, stream
import time

mcp = FastMCP("ghost-cluster", host="0.0.0.0", port=8000)

config.load_incluster_config()
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
net_v1 = client.NetworkingV1Api()

WRITE_NS = {"workload", "security", "logging", "networking"}

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

@mcp.tool()
def describe_pod(namespace: str, name: str) -> str:
    pod = v1.read_namespaced_pod(name=name, namespace=namespace)
    conditions = "\n".join([f"  {c.type}: {c.status}" for c in (pod.status.conditions or [])])
    containers = "\n".join([f"  {c.name}: {c.image}" for c in pod.spec.containers])
    return f"Name: {pod.metadata.name}\nNamespace: {pod.metadata.namespace}\nPhase: {pod.status.phase}\nConditions:\n{conditions}\nContainers:\n{containers}"

@mcp.tool()
def get_resource_quota(namespace: str) -> str:
    quotas = v1.list_namespaced_resource_quota(namespace)
    if not quotas.items:
        return f"no resource quotas found in {namespace}"
    out = []
    for q in quotas.items:
        out.append(f"Quota: {q.metadata.name}")
        for k, v_ in (q.status.hard or {}).items():
            used = (q.status.used or {}).get(k, "0")
            out.append(f"  {k}: {used}/{v_}")
    return "\n".join(out)

@mcp.tool()
def list_network_policies(namespace: str = "") -> str:
    if namespace:
        pols = net_v1.list_namespaced_network_policy(namespace)
    else:
        pols = net_v1.list_network_policy_for_all_namespaces()
    if not pols.items:
        return "no network policies found"
    return "\n".join([f"{p.metadata.namespace}/{p.metadata.name}" for p in pols.items])

@mcp.tool()
def wait_pod_ready(namespace: str, name: str, timeout: int = 60) -> str:
    start = time.time()
    while time.time() - start < timeout:
        pod = v1.read_namespaced_pod(name=name, namespace=namespace)
        phase = pod.status.phase
        if phase == "Running":
            return f"pod/{name} is Running"
        if phase in ("Failed", "Unknown"):
            return f"pod/{name} reached phase {phase}"
        time.sleep(2)
    return f"pod/{name} did not become ready within {timeout}s"

@mcp.tool()
def create_pod(namespace: str, name: str, image: str, command: list[str] = [], args: list[str] = []) -> str:
    if namespace not in WRITE_NS:
        return f"denied: {namespace} is not a writable namespace"
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(name=name, namespace=namespace),
        spec=client.V1PodSpec(
            containers=[client.V1Container(
                name=name,
                image=image,
                command=command or None,
                args=args or None
            )],
            restart_policy="Never"
        )
    )
    v1.create_namespaced_pod(namespace=namespace, body=pod)
    return f"pod/{name} created in {namespace}"

@mcp.tool()
def delete_pod(namespace: str, name: str) -> str:
    if namespace not in WRITE_NS:
        return f"denied: {namespace} is not a writable namespace"
    v1.delete_namespaced_pod(name=name, namespace=namespace)
    return f"pod/{name} deleted from {namespace}"

@mcp.tool()
def exec_pod(namespace: str, name: str, command: list[str]) -> str:
    if namespace not in WRITE_NS:
        return f"denied: {namespace} is not a writable namespace"
    resp = stream.stream(
        v1.connect_get_namespaced_pod_exec,
        name,
        namespace,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False
    )
    return resp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
