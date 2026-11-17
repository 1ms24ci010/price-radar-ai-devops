# Jenkins for Price Radar

From this folder, build a Jenkins image that includes Python 3 and Git:

```powershell
docker build -t price-radar-jenkins .
docker run -d --name price-radar-jenkins -p 8080:8080 -p 50000:50000 -v jenkins_home:/var/jenkins_home price-radar-jenkins
```

Open http://localhost:8080. Retrieve the initial password with:

```powershell
docker exec price-radar-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Install suggested plugins, including Pipeline and Git. Create a Pipeline job using Pipeline script from SCM, select Git, enter your GitHub repository URL and branch `main`, and set Build Triggers > Poll SCM to `H/1 * * * *`. This checks the repository approximately once per minute. Ensure the Jenkins host/container has outbound access to GitHub.
