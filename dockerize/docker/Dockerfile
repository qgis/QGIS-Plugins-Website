# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.13-slim AS prod

EXPOSE 8000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    git python3-dev libxml2-dev \
    libsasl2-dev libldap2-dev libssl-dev \
    libxslt1-dev zlib1g-dev \
    build-essential \
    libffi-dev gdal-bin\
    libjpeg-dev libpq-dev \
    liblcms2-dev libblas-dev \
    libmaxminddb0 libmaxminddb-dev mmdb-bin

# GeoIp mmdb
RUN apt-get update && apt-get install -y curl && curl -LJO https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb && \
    mkdir /var/opt/maxmind && \
    mv GeoLite2-City.mmdb /var/opt/maxmind/GeoLite2-City.mmdb

ENV GEOIP_PATH=/var/opt/maxmind/

RUN rm -rf /uwsgi.conf
ADD dockerize/docker/uwsgi.conf /uwsgi.conf
ADD qgis-app /home/web/django_project
ADD dockerize/docker/REQUIREMENTS.txt /REQUIREMENTS.txt

RUN pip install --upgrade pip && pip install -r /REQUIREMENTS.txt

# Install NodeJS. Node 22 is the active LTS; Node 20 went into maintenance.
#
# Certificate verification is deliberately left ON. This downloads a shell
# script and pipes it into bash as root, so --no-check-certificate (which was
# here before) meant anyone able to intercept the connection could execute
# arbitrary code inside the image at build time.
RUN apt-get -qq update && apt-get -qq install -y --no-install-recommends wget ca-certificates && \
    wget https://deb.nodesource.com/setup_22.x -O /tmp/node.sh && bash /tmp/node.sh && \
    apt-get -qq update && apt-get -qq install -y nodejs build-essential

WORKDIR /home/web/django_project
# The lockfile is copied alongside package.json so `npm ci` can install the
# exact resolved tree rather than re-resolving the caret ranges at build time.
COPY qgis-app/package.json qgis-app/package-lock.json /home/web/django_project/
# webpack and webpack-cli are NOT installed globally: they are already
# devDependencies, npm scripts resolve node_modules/.bin first, and the global
# copies were pinned separately (webpack@5.89.0, webpack-cli@5.1.4) so they
# drifted from package.json without anything noticing. npm comes from the Node
# package rather than being pinned to an older release on top of it -- the
# pinned npm@10.2.1 was from 2023 and dragged in its own vulnerable bundled
# tree (tar, sigstore, brace-expansion) that had nothing to do with this app.
RUN npm ci --unsafe-perm

# Build webpack bundles at image build time — no runtime npm needed.
RUN npm run build

# Preserve webpack-stats.json outside django_project so the devweb bind-mount
# (../qgis-app:/home/web/django_project) doesn't hide it. The startup command
# copies it back into the project dir at container start.
RUN cp /home/web/django_project/webpack-stats.json /home/web/webpack-stats.json

# Collect all static files (including webpack bundles) into a baked directory inside
# the image. DATABASE_* and RABBITMQ_HOST are required by settings.py/settings_docker.py
# at import time (os.environ[] with no default), but collectstatic never uses them.
RUN STATIC_ROOT=/home/web/static_baked/ \
    DATABASE_NAME=build \
    DATABASE_USERNAME=build \
    DATABASE_PASSWORD=build \
    DATABASE_HOST=build \
    RABBITMQ_HOST=build \
    SECRET_KEY=build \
    DJANGO_SETTINGS_MODULE=settings_docker \
    python manage.py collectstatic --noinput --skip-checks

RUN mkdir -p /var/log/uwsgi

WORKDIR /home/web/django_project
CMD ["uwsgi", "--ini", "/uwsgi.conf"]


FROM prod AS dev

# This section taken on 2 July 2015 from
# https://docs.docker.com/examples/running_ssh_service/
# Sudo is needed by pycharm when it tries to pip install packages
RUN apt-get update && apt-get install -y openssh-server sudo
RUN mkdir -p /var/run/sshd
RUN echo 'root:docker' | chpasswd
RUN echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

ENV NOTVISIBLE "in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile

# Install freezegun for feedback test
RUN pip install freezegun

# --------------------------------------------------------
# Open ports as needed
# --------------------------------------------------------

# Open port 8080 as we will be running our django dev server on
EXPOSE 8080
# Open port 22 as we will be using a remote interpreter from pycharm
EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
