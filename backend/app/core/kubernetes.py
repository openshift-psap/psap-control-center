"""Connection settings shared by the registered and management cluster clients."""

import os
from urllib.parse import urlsplit

from kubernetes import client, config


def configure_api_proxy(configuration: client.Configuration) -> None:
    # Client 34.1.0 clears no_proxy during construction. Pass exclusions to
    # the actual REST transport, including the API service IP injected by K8s.
    scheme = urlsplit(configuration.host).scheme
    if scheme in ("http", "https"):
        key = f"{scheme}_proxy"
        configuration.proxy = os.environ.get(key) or os.environ.get(key.upper()) or configuration.proxy
    exclusions = [
        configuration.no_proxy,
        os.environ.get("no_proxy") or os.environ.get("NO_PROXY"),
        os.environ.get("KUBERNETES_SERVICE_HOST"),
    ]
    configuration.no_proxy = ",".join(filter(None, exclusions)) or None


def management_configuration(kubeconfig_path: str | None) -> client.Configuration:
    configuration = client.Configuration()
    if kubeconfig_path:
        config.load_kube_config(config_file=kubeconfig_path, client_configuration=configuration)
    else:
        try:
            config.load_incluster_config(client_configuration=configuration)
        except config.ConfigException:
            config.load_kube_config(client_configuration=configuration)
    configure_api_proxy(configuration)
    return configuration
