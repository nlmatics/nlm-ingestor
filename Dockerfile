# syntax=docker/dockerfile:experimental
FROM python:3.11-bookworm
RUN apt-get update && apt-get -y --no-install-recommends install libgomp1
ENV APP_HOME /app
# install Java
RUN mkdir -p /usr/share/man/man1 && \
    apt-get update -y && \
    apt-get install -y openjdk-17-jre-headless && \
    apt-get install -y libxml2-dev && \
    apt-get install -y libxslt-dev && \
    apt-get install -y build-essential
RUN apt-get install unzip -y && \
    apt-get install git -y && \
    apt-get autoremove -y
WORKDIR ${APP_HOME}
COPY . ./
RUN pip install --upgrade pip setuptools
RUN apt-get install -y libmagic1
RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts
RUN pip install -r requirements.txt
RUN python -m nltk.downloader stopwords
RUN python -m nltk.downloader punkt
RUN chmod +x run.sh
CMD ./run.sh
