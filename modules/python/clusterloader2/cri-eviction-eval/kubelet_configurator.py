from kubernetes_client import KubernetesClient

class KubeletConfig:
    def __init__(self, eviction_hard_memory:str):
        self.eviction_hard_memory = eviction_hard_memory

    default_config = None

    def reconfigure_kubelet(self, client: KubernetesClient, node_label: str):
        print(f"Default eviction hard memory: %s, Desired eviction hard memory: %s", self.default_config.eviction_hard_memory, self.eviction_hard_memory)
        if self.default_config.eviction_hard_memory != self.eviction_hard_memory:
            client.create_daemonset("kube-system", self.generate_kubelet_reconfig_daemonset(node_label))
        else:
            print(f"Eviction hard memory is already set to {self.eviction_hard_memory}. Skip reconfiguring kubelet.")

    def generate_kubelet_reconfig_daemonset(self, node_label:str):
        kubelet_daemonset = """apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: kubelet-config-updater
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: kubelet-config-updater
  template:
    metadata:
      labels:
        app: kubelet-config-updater
    spec:
      hostPID: true
      nodeSelector:
        {node_label}: true
      containers:
      - name: kubelet-config-updater
        image: mcr.microsoft.com/cbl-mariner/busybox:2.0
        securityContext:
          privileged: true
        command:
        - /bin/sh
        - -c
        - |
          echo "Updating kubelet configuration..."
          sed -i 's/--eviction-hard=memory\.available<{default_eviction_memory}/--eviction-hard=memory\.available<{desired_eviction_memory}/' "/etc/default/kubelet"
          echo "Restarting kubelet..."
          nsenter --mount=/proc/1/ns/mnt -- systemctl restart kubelet
          echo "Done. Sleeping indefinitely to keep the pod running."
          sleep infinity
        volumeMounts:
        - name: systemd
          mountPath: /run/systemd
        - name: kubelet-config
          mountPath: /etc/default
      volumes:
      - name: kubelet-config
        hostPath:
          path: /etc/default
          type: Directory
      - name: systemd
        hostPath:
          path: /run/systemd
      restartPolicy: Always
        """
        # rewrite using string template

        evict_flag_replacement = "s/--eviction-hard=memory\.available<100Mi/--eviction-hard=memory\.available<750Mi/"
        return kubelet_daemonset.format(node_label = node_label, default_eviction_memory=self.default_config.eviction_hard_memory, desired_eviction_memory=self.eviction_hard_memory)
