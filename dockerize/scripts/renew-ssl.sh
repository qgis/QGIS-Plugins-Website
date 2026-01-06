#!/usr/bin/env bash


# Run daily on crontab e.g.
#  Your cron job will be run at: (5 times displayed)
#
#    2021-11-08 11:10:00 UTC
#    2021-11-09 11:10:00 UTC
#    2021-11-10 11:10:00 UTC
#    2021-11-11 11:10:00 UTC
#    2021-11-12 11:10:00 UTC
#    ...etc

#25 11 * * * /bin/bash /home/web/QGIS-Plugins-Website/dockerize/scripts/renew_ssl.sh > /tmp/ssl-renewal-logs.txt

# Set common variables
COMPOSE_FILE="/home/web/QGIS-Plugins-Website/dockerize/docker-compose.yml"
PROJECT_NAME="qgis-plugins"

# Renew SSL certificates
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run certbot renew

# Hot reload the web service to apply new certificates
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" kill -s SIGHUP web
