# ✨ Contributing to QGIS-Plugins-Website

Thank you for considering contributing to QGIS Plugins Website!
We welcome contributions of all kinds, including bug fixes, feature requests,
documentation improvements, and more. Please follow the guidelines below to
ensure a smooth contribution process.

## Contributions guidelines

### Reporting issues

- We do not accept text in issues/comments that are LLM (AI) generated as part of our policy (please see the [Using AI](#-using-ai-large-language-models) section for more details).
- **This repository is only for the QGIS Plugins website (plugins.qgis.org)** and we would appreciate if you could only report issues that are related to this website here.
Any issue related to other websites (e.g qgis.org) or the QGIS Desktop should be reported to their respective repository. Issues related to a specific plugin should be reported to that plugin's own bug tracker (see the metadata/details of the concerned plugin).
- If you are considering to submit a PR directly, **we recommend opening an issue first** explaining the bug or the request. That way, it can be discussed before you spend the effort addressing it.
- We recommend reporting each issue under its respective category. When pressing the **New issue** button, please choose one of `Bug Report`, `Development`, `Feature Request`, `Security Check Issue` category. Never use the `Blank issue` for any issue that is under these existing categories.
- We also recommend attaching any relevant details like screenshots, error logs, wireframe... that could help us have more context about the issue.
- When submitting an issue, you should be always responsive to any questions and concerns. If we do not get a timely response, we reserve the right to close the issue so that we can keep the list of in-play issues we have to deal with small.

### Submitting a pull request

When submitting a PR, we are expecting you take into consideration the following guidelines:

- We do not accept text in PR title/descriptions/comments that are LLM (AI) generated as part of our policy (please see the [Using AI](#-using-ai-large-language-models) section for more details).
- The PR should always include an open issue reference (e.g Fixes #1234) unless the changes have been already discussed and the full context is provided.
- Make small, atomic changes. Your changeset size should not exceed more than 300 lines of code.
- Any content, UI/UX changes must always have screenshots attached (desktop/mobile version). Screenshots are also very welcome on any other changes whenever possible.
- When submitting PR, you should be always responsive to any questions, comments and changes requests. As with open issues, we reserve the right to close PR's if we do not get needed feedback in a timely manner. We do this to keep the number of in-consideration PR's short and manageable.

### 🤖 Using 'AI' (Large Language Models)

If you follow the QGIS discussion lists, QEP's etc. you will see that the use of LLM's and QGIS' acceptance of this is still under discussion. We are not the LLM police and do not have any systematic way to check if you are using an LLM or not - we expect you to self declare your LLM usage in your PR comment. That said, we are not super enthusiastic about receiving LLM generated patches if we do not know and trust you, and suggest that if you are making your first contributions, do it the old fashioned way (using brains and brawn, not an LLM). If you are a regular contributor and we trust that that submissions you make are of a good quality, we will likely be more accepting of LLM based contributions.

**Code changes only:** As stated in our project policy in [QEP 408](https://github.com/qgis/QGIS-Enhancement-Proposals/blob/master/qep-408-ai-tool-policy.md), AI/LLM generated text content are not allowed in all QGIS GitHub repositories. This includes issues and PR titles, descriptions, comments... Only the source code changes is allowed to be generated with the help of AI/LLM.

![-----------------------------------------------------](./img/green-gradient.png)


## 🏃Before you start
 
This project requires [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) to run the development and production environments.  
Please ensure both are installed on your system before proceeding.

![Docker logo](https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png)

You can check your installation with:
```bash
docker --version
docker-compose --version
```

![-----------------------------------------------------](./img/green-gradient.png)

## 🛒 Getting the Code

- Clone the git repo

```bash
git clone https://github.com/qgis/QGIS-Plugins-Website.git
```

If the clone was succesful you should now see the directory `./QGIS-Plugins-Website`.

- Change into this project root directory

```bash
cd QGIS-Plugins-Website
```

![-----------------------------------------------------](./img/green-gradient.png)

## 🧑💻 Development

### Environment file (`.env`)

- Create .env file
```bash
cp dockerize/.env.template dockerize/.env
```

- Edit .env file and set your environment variables
- Enable debug mode by setting `DEBUG=True`.
- Uncomment RABBITMQ_IMAGE if you want to use a different image version.
  Default is `rabbitmq:3.7-alpine`. This is useful if you encounter any issues
  with the default image (can be also use to change the image without editing the code).
  Please also see [this discussion](https://github.com/qgis/QGIS-Plugins-Website/issues/80).

**IMPORTANT NOTE**: For new Django variables, please use the `settings_local.py` as the `.env` file is not supported by the new production infrastructure.

### Django Local Settings (`settings_local.py`)

- Create settings_local.py file
```bash
cp qgis-app/settings_local.py.templ qgis-app/settings_local.py
```

- Edit settings_local.py file and set your environment variables

**IMPORTANT NOTE**: As we are migrating to a declarative based infrastructure, it is preferable to use the `settings_local.py` file for all new Django variables. This file is ignored when commiting so please make sure you define your new variables with an example value (**NOT THE REAL ONE FOR SECRETS AND PASSWORDS**) inside the `settings_local.py.templ` file.

### Spin up the development environment

- Change to the `dockerize` directory

```bash
cd dockerize
```

- Build and spin container
```bash
make devweb-config build
make devweb
```

- Run migrate and seed db
```bash
make devweb-migrate
make dbseed
```

If you have a backup, you can restore it:

```bash
make dbrestore
```

- Set up python interpreter in PyCharm or just runserver from devweb container:
```bash
make devweb-runserver
```
and now, you can see your site at `http://localhost:62202` `http://0.0.0.0:62202`.

- Run unit tests
```bash
make devweb-runtests
```

- You can use the following credentials to log in if you ran the `make dbseed` command:

```text
Admin account:
username: admin
password: admin

Staff account:
username: staff
password: staff

Plugin author account:
username: creator
password: creator
```

- Update migrations:
```bash
make devweb-makemigrations app='plugins'
```

- Run a django command from the devweb container
```bash
make devweb-exec c='python manage.py createsuperuser'
make devweb-exec c='pip freeze'
```

- Enter the devweb container shell
```bash
make devweb-shell
```

- If 'None' appears in the search results, it indicates a misalignment between the search index and the database. This discrepancy often arises when a plugin is deleted from the model but persists in the search index. To rectify this issue, it is essential to synchronize the search index with the database by rebuilding it. Execute the following command to initiate the rebuilding process:

```bash
make rebuild_index
```
This command ensures that the search index accurately reflects the current state of the database, resolving the presence of 'None' in the search results. Automatic synchronization is currently managed in settings.py: `HAYSTACK_SIGNAL_PROCESSOR = "haystack.signals.RealtimeSignalProcessor"`.

For more information about make commands, please see the full docs [here](./dockerize/README.md).

For development in a containerized environment using VSCode:

- Install the [Remote Development extension pack](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.vscode-remote-extensionpack) in VSCode to enable attaching to and developing inside containers.

- Attach to the `qgis-plugins-devweb` container to work on the website.

- For pre-commit and git hooks:
  
  1. Install dependencies inside the `maindev` container:

    ```bash
    make maindev-install-dep
    ```

  2. Attach to the `qgis-plugins-maindev` container to run pre-commit checks and perform git operations. The repository is located at `/srv/app` within the container.

### Nix

Run the following command on this project root folder:

```sh
nix-shell
./vscode.sh
```
TODO: Install all dependecies when running nix-shell.


### Setup git-hooks and local linting

In the root directory of the repo, run:

```bash
pip install -r REQUIREMENTS-dev.txt

pre-commit install --config .pre-commit-config.yaml
```


### Setting up a remote interpreter in PyCharm

- PyCharm -> Preferences -> Project: QGIS-Plugins-Website
- Click on the gear icon next to project interpreter -> add
- SSH Interpreter -> New server configuration
- Host : `localhost`
- Port : `62203`
- Username: `root`
- Click next button
- Auth type: password (and tick 'save password')
- Click next button
- password : `docker`
- Interpreter : `/usr/local/bin/python`
- Sync folders -> click on the folder icon
  - local : `<path to your repo>/dockerize/qgis-app`
  - remote : `/home/web/django_project`
    After that you should see something like this in sync folder:
    `<Project root>/django_project→/home/web/django_project`
- Automatically upload project files to the server -> untick the checkbox to avoid overwriting in your files.
- Click the Apply button


#### In settings, django support:

- Language & Framework -> Django
- tick to Enable Django Support.
- Django project root: `<path to your repo>/qgis_app`
- Settings: setting_docker.py
- Click the Apply button

#### Create the django run configuration

- Run -> Edit configurations
- Click the `+` icon in the top left corner
- Choose `Django server` from the popup list

Now set these options:

- **Name:** Django Server
- **Host:** 0.0.0.0
- **Port:** 8080
- **Additional options:** `--settings=settings.docker`
- **Run browser** If checked, it will open the url after you click run. You should be able to access the running on 0.0.0.0:62202 (the port that mapped to 8080)

* **Environment vars** , you can add the variables value one-by-one by clicking on browse icon at right corner in the input field, or just copy-paste this value:
`PYTHONUNBUFFERED=1;DJANGO_SETTINGS_MODULE=settings_docker;RABBITMQ_HOST=rabbitmq;DATABASE_NAME=gis;DATABASE_USERNAME=docker;DATABASE_PASSWORD=docker;DATABASE_HOST=db`
* **Python interpreter:** Ensure it is set you your remote interpreter (should be
  set to that by default)

* **Path mappings:** Here you need to indicate path equivalency between your host
  filesystem and the filesystem in the remote (docker) host. Click the ellipsis
  and add a run that points to your git checkout on your local host and the
  /home/web directory in the docker host. e.g.
  * **Local path:** <path to your git repo>/QGIS-Plugins-Website/qgis-app
  * **Remote path:** /home/web/django_project
* click OK to save your run configuration

Now you can run the server using the green triangle next to the Django server
label in the run configurations pull down. Debug will also work and you will be
able to step through views etc as you work.


![-----------------------------------------------------](./img/green-gradient.png)

## Backup and Restore

- Go to repo directory and run backup.sh
```bash
./backup.sh
```
- You will find dumps file in backups directory
```bash
tree -L 3 backups
```

Example output:

```text
backups
├── 2016
├── 2017
├── 2018
├── 2019
├── 2020
│   ├── April
│   │   └── PG_QGIS_PLUGINS_gis.07-April-2020.dmp
│   ├── August
│   ├── December
│   │   ├── PG_QGIS_PLUGINS_gis.01-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.02-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.03-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.04-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.05-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.06-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.07-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.08-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.09-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.10-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.11-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.12-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.13-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.14-December-2020.dmp
│   │   ├── PG_QGIS_PLUGINS_gis.15-December-2020.dmp
│   │   └── PG_QGIS_PLUGINS_gis.16-December-2020.dmp
│
```

- Copy the dump file you wish to restore to dockerize/backups/latest.dmp file
```bash
cp backups/2020/December/PG_QGIS_PLUGINS_gis.16-December-2020.dmp dockerize/backups/latest.dmp
```

- Restore the dump file
```bash
cd dockerize
make dbrestore
```
![-----------------------------------------------------](./img/green-gradient.png)

## 🌐 Deployment

For the production environment, please see the the private repo of the System Administration Documentation.

![-----------------------------------------------------](./img/green-gradient.png)
