#!/bin/bash
# latest version of java and a python environment where requirements are installed is required
nohup java -jar jars/tika-server-standard-nlm-modified-2.9.2_v2.jar > /dev/null 2>&1 &
python -m nlm_ingestor.ingestion_daemon