# Price Radar AI — DevOps Assignment

This repository packages the existing Price Radar AI Flask application for the DevOps coursework. It retains the product watchlist, SQLite-backed price history, target/drop alert rules, in-app notifications, product review analysis, and optional n8n webhook integrations.

## Important functionality and data-source boundaries

- Price changes in this coursework build are recorded through the app's test/manual observation flow; it does not fetch live Amazon, Flipkart, or Myntra prices automatically.
- The bundled review dataset is synthetic demonstration data. The review analysis endpoint can send it to the configured n8n/Gemini workflow, but it is not a live marketplace review collector.
- Email delivery is routed through `N8N_EMAIL_WEBHOOK_URL`; actual delivery requires a configured and tested n8n email workflow.
- Do not commit webhook URLs, credentials, `.env`, or a personal `price_radar.db`. The database is intentionally excluded because it can contain product URLs, watchlist information, notification preferences, and email addresses. A new database is created automatically.
- Kubernetes replicas use separate ephemeral SQLite files (`emptyDir`). This is adequate for demonstrating replicas, Service routing, health probes and scaling; it is not a production shared-database design.

## Local Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`. Check `http://127.0.0.1:5000/health`.

Run tests:

```powershell
python -m pytest -v
```

## Git workflow evidence

Create real feature branches and merge them into `main` using GitHub pull requests. Suggested sequence:

1. Initial commit: existing Price Radar application and safe repository hygiene.
2. `feature/health-check-tests`: health endpoint and pytest suite; open and merge a pull request.
3. `feature/ci-pipeline`: Jenkinsfile and GitHub Actions workflow; open and merge a pull request.
4. `feature/container-deployment`: Dockerfile and Kubernetes manifests; open and merge a pull request.
5. `feature/ansible-setup`: Ansible inventory, playbook and role; open and merge a pull request.

Use actual commits as you complete each stage. Do not fabricate commit dates or history.

## Component 1 — CI

### GitHub Actions

The workflow at `.github/workflows/ci.yml` installs Python dependencies and runs pytest on pushes to `main`/`feature/**` and pull requests to `main`.

### Jenkins

Build the Python-enabled Jenkins image using the instructions in `jenkins/README.md`. Create a Pipeline job configured as Pipeline script from SCM, point it to this repository and branch `main`, and enable Poll SCM with `H/1 * * * *`. The `Jenkinsfile` runs tests and archives a source tarball. Push a small change and capture the automatically triggered build.

## Component 2 — Ansible, Docker and Kubernetes

### Docker

```powershell
docker build -t price-radar:1.0 .
docker run --rm -p 5000:5000 -v price-radar-data:/data price-radar:1.0
```

### Ansible

Run from Ubuntu/WSL2 with systemd enabled. From the repository root:

```bash
sudo apt update
sudo apt install -y ansible
cd ansible
ansible-playbook -i inventory.ini site.yml
```

The role installs Python, copies the app and assets, creates a virtual environment, installs dependencies, and manages a systemd service. It demonstrates variables, a role and a restart handler.

### Kubernetes with Minikube

From PowerShell at the repository root:

```powershell
minikube start
minikube image build -t price-radar:1.0 .
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl get pods
kubectl get svc
kubectl scale deployment/price-radar --replicas=5
kubectl get pods
kubectl scale deployment/price-radar --replicas=3
kubectl get pods
minikube service price-radar-service
```

Each pod gets its own ephemeral SQLite database. Do not use this setup for shared production data.

## Evidence to capture

- GitHub branches, commits and merged pull requests.
- GitHub Actions successful run.
- Jenkins job configuration, automatic build console output and archived artifact.
- Ansible playbook successful output.
- Docker image build and container response.
- Kubernetes pods at 3, then 5, then 3 replicas; Service output; successful `/health` response.
- ConfigMap and liveness/readiness probe configuration.

## Submission

Add the course coordinator as a repository collaborator. Put the repository URL in the report and `repo_link.txt`. Complete the report sections for both components using genuine screenshots and results.



## Health Check API

The application provides a health check endpoint:

GET /health

It returns the application status and can be used by
CI/CD pipelines and Kubernetes health probes.