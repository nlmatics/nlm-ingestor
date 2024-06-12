# syntax=docker/dockerfile:experimental
FROM python:3.11-bookworm
RUN apt-get update && apt-get -y --no-install-recommends install libgomp1
ENV APP_HOME /app
# install Java
RUN mkdir -p /usr/share/man/man1 && \
  apt-get update -y && \
  apt-get install -y openjdk-17-jre-headless
# install essential packages
RUN apt-get install -y \
  libxml2-dev libxslt-dev \
  build-essential libmagic-dev
# install tesseract
RUN apt-get install -y \
  tesseract-ocr \
  lsb-release \
  && echo "deb https://notesalexp.org/tesseract-ocr5/$(lsb_release -cs)/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/notesalexp.list > /dev/null \
  && apt-get update -oAcquire::AllowInsecureRepositories=true \
  && apt-get install notesalexp-keyring -oAcquire::AllowInsecureRepositories=true -y --allow-unauthenticated \
  && apt-get update \
  && apt-get install -y \
  tesseract-ocr libtesseract-dev \
  && wget -P /usr/share/tesseract-ocr/5/tessdata/ https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata
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
RUN python -c "import tiktoken; tiktoken.get_encoding(\"cl100k_base\")"
RUN chmod +x run.sh
EXPOSE 5001
CMD ./run.sh
