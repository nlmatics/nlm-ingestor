# syntax=docker/dockerfile:experimental
FROM python:3.11-bookworm

# Update and upgrade system packages to get the latest security fixes
RUN apt-get update && apt-get upgrade -y && \
  apt-get install -y --no-install-recommends libgomp1 && \
  rm -rf /var/lib/apt/lists/*

ENV APP_HOME /root
ENV PYTHONPATH="${PYTHONPATH}:${APP_HOME}"
ENV PYTHONUNBUFFERED=1

# install Java
RUN mkdir -p /usr/share/man/man1 && \
  apt-get update && apt-get install -y openjdk-17-jre-headless && \
  rm -rf /var/lib/apt/lists/*

# install essential packages
RUN apt-get update && apt-get install -y \
  libxml2-dev libxslt-dev \
  build-essential libmagic-dev && \
  rm -rf /var/lib/apt/lists/*

# install tesseract and related dependencies
RUN apt-get update && apt-get install -y \
  tesseract-ocr lsb-release && \
  echo "deb https://notesalexp.org/tesseract-ocr5/$(lsb_release -cs)/ $(lsb_release -cs) main" \
  | tee /etc/apt/sources.list.d/notesalexp.list > /dev/null && \
  apt-get update -oAcquire::AllowInsecureRepositories=true && \
  apt-get install -y notesalexp-keyring -oAcquire::AllowInsecureRepositories=true --allow-unauthenticated && \
  apt-get update && \
  apt-get install -y tesseract-ocr libtesseract-dev && \
  wget -P /usr/share/tesseract-ocr/5/tessdata/ \
  https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata && \
  rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y unzip git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR ${APP_HOME}
COPY . ./

RUN pip install --upgrade pip setuptools

RUN apt-get update && apt-get install -y libmagic1 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts
RUN pip install -e .
RUN python -m nltk.downloader stopwords
RUN python -m nltk.downloader punkt
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
RUN chmod +x run.sh

EXPOSE 5001
# CMD ./run.sh