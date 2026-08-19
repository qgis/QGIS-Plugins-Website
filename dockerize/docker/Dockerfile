# Three stages: builder -> prod -> dev.
#
# The production image used to be a single stage, so everything needed to
# *build* the application also shipped to production and ran on an
# internet-facing host: a C toolchain, git, curl, Node and npm, the GDAL
# command line utilities, and a second system Python. None of it is executed at
# runtime. In the v4.3.0 scan those build-only packages accounted for roughly
# 640 of the 1346 CVE findings -- binutils and build-essential alone contributed
# 456 -- plus the entire npm dependency tree, which contained the only Critical
# finding that no Node release could fix, because it lives inside npm's own
# bundle rather than in anything this application depends on.
#
# So: compile in `builder`, copy the results into a `prod` stage that installs
# runtime shared libraries only, and let `dev` add back the things developers
# need (Node for the webpack watcher, sshd for remote interpreters).
#
# Python packages are installed into a virtualenv at /opt/venv so the runtime
# stage can take them as one self-contained directory. This only works because
# both stages use the identical base image -- keep the two FROM lines in sync.

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Build-time only. The -dev packages provide headers for the requirements that
# compile from source (uwsgi, python-ldap, Pillow, psycopg); git is needed for
# the three REQUIREMENTS entries installed from GitHub commits.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libffi-dev \
        libgdal-dev \
        libjpeg-dev \
        liblcms2-dev \
        libldap2-dev \
        libmaxminddb-dev \
        libpq-dev \
        libsasl2-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        python3-dev \
        wget \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY dockerize/docker/REQUIREMENTS.txt /REQUIREMENTS.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /REQUIREMENTS.txt

# GeoIP database, consumed at runtime through GEOIP_PATH.
RUN mkdir -p /var/opt/maxmind \
    && curl -fsSL -o /var/opt/maxmind/GeoLite2-City.mmdb \
        https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb

# Node 22 is the active LTS; Node 20 is in maintenance.
#
# Certificate verification is deliberately left ON. This downloads a shell
# script and pipes it into bash as root, so --no-check-certificate (which was
# here before) meant anyone able to intercept the connection could execute
# arbitrary code inside the image at build time.
RUN wget https://deb.nodesource.com/setup_22.x -O /tmp/node.sh \
    && bash /tmp/node.sh \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home/web/django_project

# Dependencies before sources, so editing the app does not invalidate the npm
# layer. The lockfile is copied alongside package.json so `npm ci` installs the
# exact resolved tree rather than re-resolving the caret ranges at build time.
#
# webpack and webpack-cli are NOT installed globally: they are already
# devDependencies and npm scripts resolve node_modules/.bin first. npm itself
# comes from the Node package rather than being pinned to an older release on
# top of it.
COPY qgis-app/package.json qgis-app/package-lock.json ./
RUN npm ci --unsafe-perm

COPY qgis-app /home/web/django_project
RUN npm run build

# Move node_modules out of the application directory so the prod stage can copy
# the built application without it. 45MB of build-time JavaScript that is never
# executed by the running site, and the source of every npm CVE in the scan.
# The dev stage puts it back.
RUN mv /home/web/django_project/node_modules /opt/node_modules


FROM python:3.13-slim AS prod

EXPOSE 8000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Runtime shared libraries only -- no compilers, no headers, no git, no curl.
#
#   libgdal36, libgeos-c1t64  GeoDjango: settings_docker.py uses the
#                             django.contrib.gis.db.backends.postgis engine,
#                             which loads both through ctypes. Note this is
#                             libgdal only: gdal-bin pulls in the CLI utilities
#                             and python3-gdal, which drag a whole second
#                             system Python in with them, and nothing uses it.
#   libpq5                    psycopg
#   libldap2, libsasl2-2      python-ldap, which settings.py imports at module
#                             scope via settings_auth -- unconditionally, even
#                             when ENABLE_LDAP is False. A missing lib here is
#                             an immediate boot failure, not a lazy one.
#   libmaxminddb0             geoip2
#   libjpeg62-turbo, liblcms2-2   Pillow
#
# libxml2/libxslt are deliberately absent: nothing imports lxml, and
# BeautifulSoup is used with the stdlib html.parser.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgdal36 \
        libgeos-c1t64 \
        libjpeg62-turbo \
        liblcms2-2 \
        libldap2 \
        libmaxminddb0 \
        libpq5 \
        libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv

COPY --from=builder /var/opt/maxmind /var/opt/maxmind
ENV GEOIP_PATH=/var/opt/maxmind/

COPY dockerize/docker/uwsgi.conf /uwsgi.conf

# The application, including the webpack bundles built in the builder stage but
# not the node_modules they were built from.
COPY --from=builder /home/web/django_project /home/web/django_project

# Preserve webpack-stats.json outside django_project so the devweb bind-mount
# (../qgis-app:/home/web/django_project) doesn't hide it. The startup command
# copies it back into the project dir at container start.
RUN cp /home/web/django_project/webpack-stats.json /home/web/webpack-stats.json

# Collect all static files (including webpack bundles) into a baked directory inside
# the image. DATABASE_* and RABBITMQ_HOST are required by settings.py/settings_docker.py
# at import time (os.environ[] with no default), but collectstatic never uses them.
WORKDIR /home/web/django_project
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

CMD ["uwsgi", "--ini", "/uwsgi.conf"]


FROM prod AS dev

# Node comes back for the `webpack` compose service, which runs `npm start`.
# sshd is here so PyCharm can attach a remote interpreter; sudo because it
# wants to pip install as root.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        openssh-server \
        sudo \
        wget \
    && wget https://deb.nodesource.com/setup_22.x -O /tmp/node.sh \
    && bash /tmp/node.sh \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/node_modules /home/web/django_project/node_modules

# This section taken on 2 July 2015 from
# https://docs.docker.com/examples/running_ssh_service/
RUN mkdir -p /var/run/sshd \
    && echo 'root:docker' | chpasswd \
    && echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

ENV NOTVISIBLE="in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile

# Install freezegun for feedback test
RUN pip install --no-cache-dir freezegun

# --------------------------------------------------------
# Open ports as needed
# --------------------------------------------------------

# Open port 8080 as we will be running our django dev server on
EXPOSE 8080
# Open port 22 as we will be using a remote interpreter from pycharm
EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
