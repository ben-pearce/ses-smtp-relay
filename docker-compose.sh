#!/usr/bin/env bash

BASEDIR=$(dirname "$0")
/usr/bin/docker compose -f docker-compose.yml $(find $BASEDIR/*.org.docker-compose.yml | sed -e 's/^/-f /') "$@"