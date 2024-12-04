#!/bin/bash
# latest version of java and a python environment where requirements are installed is required
nohup java -jar jars/tika-server-standard-nlm-modified-2.9.2_v2.jar > /dev/null 2>&1 &

gunicorn -b 0.0.0.0:5001 nlm_ingestor.ingestion_daemon.__main__:app
