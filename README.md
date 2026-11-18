# Price Radar AI — DevOps Deployment Project

A Flask-based Price Radar AI application used to demonstrate source control, continuous integration, configuration management, containerization, Kubernetes deployment, health checks, and horizontal scaling.

**GitHub repository:** https://github.com/1ms24ci010/price-radar-ai-devops

---

## 1. Project Overview

This project applies a DevOps workflow to the Price Radar AI application. The source code is maintained in GitHub, Jenkins runs the CI pipeline, Ansible automates host-level application setup, Docker packages the application into an image, and Kubernetes manages the containerized application.

### DevOps workflow

1. **Source control:** Git and GitHub manage the application source and changes.
2. **Continuous Integration:** Jenkins checks out the repository, installs dependencies, runs the automated test stage, packages the source, and archives the generated artifact.
3. **Configuration management:** Ansible uses an inventory, playbook, variables, tasks, handler, and role to configure and run the application as a systemd service.
4. **Containerization:** Docker builds the application image.
5. **Orchestration:** Kubernetes deploys multiple replicas and exposes the application through a NodePort Service.
6. **Health and scaling:** Kubernetes liveness/readiness probes check the `/health` endpoint, and the Deployment can be scaled.

---

## 2. Technologies Used

- Python and Flask
- Git and GitHub
- Jenkins
- Docker
- Ansible
- Kubernetes
- YAML
- Windows PowerShell and Ubuntu on WSL 2
- Docker Desktop with the `docker-desktop` Kubernetes context

---

## 3. Repository Structure

```text
Price-Radar-DevOps/
├── ansible/
│   ├── inventory.ini
│   ├── playbook.yml
│   └── roles/
│       └── price_radar/
│           ├── defaults/
│           │   └── main.yml
│           ├── handlers/
│           │   └── main.yml
│           ├── tasks/
│           │   └── main.yml
│           └── templates/
│               └── price-radar.service.j2
├── k8s/
│   ├── configmap.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── Dockerfile
├── Jenkinsfile
├── requirements.txt
└── README.md
```

The application source files and any additional static/template directories are kept in the repository alongside these DevOps configuration files.

---

## 4. Git and GitHub

The project is maintained in a GitHub repository. A feature branch was created for the health-check documentation, and the changes were merged into `main` using a merge commit.

Useful commands:

```bash
git status
git branch
git log --oneline --graph --all
git checkout -b feature/branch-name
git add .
git commit -m "Describe the change"
git push -u origin feature/branch-name
```

The final Ansible and Kubernetes configuration changes were committed and pushed to `main`.

---

## 5. Jenkins Continuous Integration

Jenkins is configured with a Pipeline job named `Price-Radar-CI`.

### Pipeline configuration

- Pipeline source: GitHub repository
- Branch: `*/main`
- Pipeline script path: `Jenkinsfile`
- SCM polling is configured in the Jenkinsfile to check for repository changes periodically.

### Pipeline stages

The pipeline contains the following stages:

1. **Checkout:** Retrieves the source code from the configured GitHub repository.
2. **Install dependencies:** Installs the Python packages required by the application.
3. **Run automated tests:** Executes the project's automated test stage.
4. **Package application:** Creates a compressed source archive.

The generated `price-radar-source.tar.gz` file is archived as a Jenkins build artifact.

### Running the pipeline

1. Open the Jenkins dashboard.
2. Select `Price-Radar-CI`.
3. Select **Build Now** to run the pipeline manually.
4. Open the build number and inspect **Console Output**.
5. Confirm that the build finishes successfully.
6. Open the build's **Artifacts** section to view `price-radar-source.tar.gz`.

---

## 6. Ansible Configuration Management

Ansible is used to configure the local Ubuntu/WSL environment and manage the Price Radar application as a systemd service.

### Inventory

`ansible/inventory.ini`:

```ini
[price_radar]
localhost ansible_connection=local
```

### Playbook

`ansible/playbook.yml`:

```yaml
---
- name: Deploy Price Radar application
  hosts: price_radar
  become: true
  roles:
    - price_radar
```

### Role components

The `price_radar` role separates deployment configuration into reusable components:

- `defaults/main.yml`: Default variables such as the application port, application directory, data directory, and service name.
- `tasks/main.yml`: Tasks to install the required runtime, create the service account and directories, deploy application files, create the virtual environment, install dependencies, and configure/start the service.
- `handlers/main.yml`: Defines the service restart handler.
- `templates/price-radar.service.j2`: Jinja2 template for the systemd service unit.

The Ansible application port is set to **5001** to avoid a conflict with the already-running application container using port 5000 on the host.

### Run the playbook

From the project directory in Ubuntu/WSL:

```bash
sudo ansible-playbook -i ansible/inventory.ini ansible/playbook.yml
```

Check the service:

```bash
sudo systemctl status price-radar
sudo systemctl is-enabled price-radar
```

The playbook completed successfully, and the service was reported healthy during verification.

---

## 7. Docker Containerization

Docker packages the Flask application and its runtime dependencies into an image.

The image used by the Kubernetes Deployment is:

```text
price-radar-ai:1.0
```

Build the image from the project root (PowerShell or a terminal with Docker access):

```powershell
docker build -t price-radar-ai:1.0 .
```

Verify that the image exists:

```powershell
docker image inspect price-radar-ai:1.0 --format "{{.RepoTags}}"
```

The expected repository tag is `price-radar-ai:1.0`.

---

## 8. Kubernetes Deployment

The Kubernetes manifests are stored in the `k8s/` directory. The project was deployed to the Docker Desktop Kubernetes cluster.

### ConfigMap

`k8s/configmap.yaml` provides application environment configuration, including:

- `APP_HOST`
- `APP_PORT`
- `FLASK_DEBUG`
- `DATABASE_PATH`

### Deployment

`k8s/deployment.yaml` defines:

- Deployment name: `price-radar`
- Initial replica count: `3`
- Container image: `price-radar-ai:1.0`
- Container port: `5000`
- ConfigMap-based environment variables
- Application data volume mount
- Liveness and readiness HTTP probes using `/health`
- CPU and memory requests/limits

The deployment uses `imagePullPolicy: IfNotPresent`, allowing Kubernetes to use the image already available to the local Docker Desktop cluster.

### Service

`k8s/service.yaml` defines a NodePort Service:

- Service name: `price-radar-service`
- Service type: `NodePort`
- Service port: `5000`
- Target port: `5000`
- Configured NodePort: `30080`

### Apply the manifests

From the project root in PowerShell:

```powershell
kubectl config current-context
kubectl get nodes
kubectl apply -f .\k8s\
```

Check the resources:

```powershell
kubectl get deployments
kubectl get pods
kubectl get services
kubectl describe service price-radar-service
```

---

## 9. Health-check Verification

The application exposes a `/health` endpoint. Kubernetes uses this endpoint for its liveness and readiness probes.

To check the endpoint from inside a running pod:

```powershell
kubectl get pods
kubectl exec <pod-name> -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=5).read().decode())"
```

The verified response was:

```json
{"application":"Price Radar AI","status":"healthy"}
```

To access the Service locally using port forwarding, run:

```powershell
kubectl port-forward service/price-radar-service 8081:5000
```

Keep that terminal open. In a second PowerShell window, run:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/health
```

The health endpoint was successfully accessed through this port-forward.

**Networking note:** The Service manifest configures NodePort `30080`, but direct access to `http://localhost:30080/health` from the Windows host was not successful in this setup. Port-forwarding on `8081` was used for the successful host-side health-check demonstration. The NodePort configuration and the port-forward verification are separate facts.

---

## 10. Kubernetes Scaling Demonstration

The Deployment was scaled from three replicas to five and then returned to three replicas.

### Scale from 3 to 5

```powershell
kubectl scale deployment price-radar --replicas=5
kubectl rollout status deployment/price-radar
kubectl get pods
kubectl get deployments
```

### Scale from 5 back to 3

```powershell
kubectl scale deployment price-radar --replicas=3
kubectl rollout status deployment/price-radar
kubectl get pods
kubectl get deployments
```

The scaling demonstration completed successfully. The final desired replica count is three.

---

## 11. Verification Summary

The following project operations were completed and verified during the assignment:

- Git feature branch and merge workflow.
- Jenkins pipeline completed successfully.
- Jenkins archived `price-radar-source.tar.gz`.
- Ansible playbook completed without failed tasks.
- Ansible-managed Price Radar service reported healthy.
- Docker image `price-radar-ai:1.0` was present.
- Kubernetes Deployment reached three running replicas.
- Kubernetes Service was created as a NodePort Service.
- Kubernetes health endpoint returned a healthy response.
- Kubernetes scaling from 3 to 5 and back to 3 was completed.

---

## 12. Notes and Limitations

- The Ansible service runs on host port `5001` because port `5000` was already occupied in the host environment.
- The Kubernetes container listens on port `5000`; this is independent of the Ansible host service port.
- The Kubernetes Deployment currently uses an `emptyDir` volume for `/data`. This is temporary pod storage and is not persistent across pod replacement. It is suitable for this deployment demonstration, but a PersistentVolume and PersistentVolumeClaim would be needed for durable database storage.
- The Kubernetes Service's NodePort is configured as `30080`. The successful host-side health check was performed using `kubectl port-forward` on local port `8081`.
- The Jenkins pipeline was confirmed successful when run from the Jenkins job. SCM polling is configured; automatic push-trigger behavior should only be claimed if separately tested.

---

## 13. Repository

**GitHub:** https://github.com/1ms24ci010/price-radar-ai-devops

This repository contains the application and the DevOps configuration used for the assignment.
