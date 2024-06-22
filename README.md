# About

This repo provides the service code for [llmsherpa](https://github.com/nlmatics/llmsherpa) API to connect. 
This repo contains custom RAG (retrieval augmented generation) friendly parsers for the following file formats:
### PDF
The PDF parser is a rule based parser which uses text co-ordinates (boundary box), graphics and font data from nlmatics modified version of tika found here https://github.com/nlmatics/nlm-tika.
The PDF parser works off text layer and also offers a OCR option (apply_ocr) to automatically use OCR if there are scanned pages in your PDFs. The OCR feature is based off a nlmatics modified version of tika which uses tesseract underneath.
Check out the notebook [pdf_visual_ingestor_step_by_step](notebooks/pdf_visual_ingestor_step_by_step.ipynb) to experiment directly with the PDF parser.

The PDF Parser offers the following features:

1. Sections and subsections along with their levels.
2. Paragraphs - combines lines.
3. Links between sections and paragraphs.
5. Tables along with the section the tables are found in.
6. Lists and nested lists.
7. Join content spread across pages.
8. Removal of repeating headers and footers.
9. Watermark removal.
10. OCR with boundary boxes

### HTML
A special HTML parser that creates layout aware blocks to make RAG performance better with higher quality chunks. 
### Text
A special text parser which tries to figure out lists, tables, headers etc. purely by looking at the text and no visual, font or bbox information.
### DOCX, PPTX and any other format supported by Apache Tika
There are two ways to process these types of documents
- html output from tika for these file types is used and parsed by the html parser

## Installation steps:
### Run each step directly
1. Install latest version of java from https://www.oracle.com/java/technologies/downloads/
2. Run the tika server:
```
java -jar <path_to_nlm_ingestor>/jars/tika-server-standard-nlm-modified-2.9.2_v2.jar
```
3. Install the ingestor
```
!pip install nlm-ingestor
```
4. Run the ingestor
```
python -m nlm_ingestor.ingestion_daemon
```
### Run the docker file
A docker image is available via public github container registry. 

Pull the docker image
```
docker pull ghcr.io/nlmatics/nlm-ingestor:latest
```
Run the docker image mapping the port 5001 to port of your choice. 
```
docker run -p 5010:5001 ghcr.io/nlmatics/nlm-ingestor:latest-<version>
```
Once you have the server running, you can use the [llmsherpa](https://github.com/nlmatics/llmsherpa) API library to get chunks and use them for your LLM projects. Your llmsherpa_url will be:
"http://localhost:5010/api/parseDocument?renderFormat=all"
- to apply OCR add &applyOcr=yes
- to use the new indent parser which uses a different algorithm to assign header levels, add &useNewIndentParser=yes
- this server is good for your development - in production it is recommended to run this behind a secure gateway using nginx or cloud gateways

### Test the ingestor server
Sample test code to test the server with llmsherpa parser is in this [notebook](notebooks/test_llmsherpa_api.ipynb).

## Rule based parser vs model based parser
Over the course of 4 years, nlmatics team evaluated a variety of options including a yolo based vision parser developed by Tom Liu and Yi Zhang. Ultimately, we settled with the rule based parser due to the following reasons.
1. It is substantially (100x) faster compared to any vision parser as bare miniumum you have to create images out of all pages of a PDF (even for the ones with text layer) to use a vision parser. It is our opinion that vision parser is a better option for OCRd PDF without a text layer, or for small PDF files consisting form like data, but for larger text layer PDFs, spanning hundreds of pages, a rule based parser like ours is more practical.
2. No special hardware is needed to run this parser if you are not using the PDF OCR feature. You can run this with hardware from early 2000s!
3. We found vision parser (or any parser for that matter including this) to be error prone and the solution to fix errors in a model were not pretty:
    - Add more examples to your training set which may make the accuracy of the model from previous learning degrade and result in uncertainty in previously working code
    - Using rule based ideas to fix model based parser issue gets us back to writing a lot of rules again.

## Credits
The PDFparser [visual_ingestor](nlm_ingestor/ingestor/visual_ingestor/visual_ingestor.py) and [new_indent_parser](nlm_ingestor/ingestor/visual_ingestor/new_indent_parser.py) was written by Ambika Sukla with additional contributions from Reshav Abraham who wrote the initial code to modify tika, Tom Liu who wrote the original Indent Parser and Kiran Panicker who made several improvements to the parsing speed, table parsing accuracy, indent parsing accuracy and reordering accuracy. 

The [HTML Ingestor](nlm_ingestor/ingestor/html_ingestor.py) was written by Tom Liu.

The [Markdown Parser](nlm_ingestor/file_parser/markdown_parser.py) was written by Yi Zhang.

The [Text Ingestor](nlm_ingestor/ingestor/text_ingestor.py) was written by Reshav Abraham.

The [XML Ingestor](nlm_ingestor/ingestor/xml_ingestor.py) was written by Ambika Sukla primarily to process PubMed XMLs.

The [line_parser](nlm_ingestor/ingestor/line_parser.py) which serves as a core sentence processing utility for all the other parsers was written by Ambika Sukla. 

Also we are thankful to the Apache PDFBox and Tika developer community for their years of work in providing the base for the PDF Parser. 

## Nlm Modified Tika
Nlm modified version of Tika can be found in the 2.4.1-nlm branch here https://github.com/nlmatics/nlm-tika/tree/2.4.1-nlm
For convenience, a compiled jar file of the code is included in this repo in jars/ folder.
In some cases, your PDFs may result in errors in the Java server and you will need to modify the code there to resolve the issue and recompile the jar file.

The following files are changed: 

1) https://github.com/nlmatics/nlm-tika/blob/2.4.1-nlm/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-pdf-module/src/main/java/org/apache/tika/parser/pdf/PDF2XHTML.java
2) https://github.com/nlmatics/nlm-tika/blob/2.4.1-nlm/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-pdf-module/src/main/java/org/apache/tika/parser/pdf/AbstractPDF2XHTML.java

The above is to add font and co-ordinates to every text element. It also removes watermarks.

3) https://github.com/nlmatics/nlm-tika/blob/2.4.1-nlm/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-pdf-module/src/main/java/org/apache/tika/parser/pdf/GraphicsStreamProcessor.java

The above is to add lines and rectangles that can potentially help with table detection.

To see the impact of these changes, see the first part of the notebook here: https://github.com/nlmatics/nlm-ingestor/blob/main/notebooks/pdf_visual_ingestor_step_by_step.ipynb

Some ideas for future work:
1) Make the changes independent of tika by writing own wrapper over pdfbox
2) Upgrade to latest version of tika 
3) Cleanup the format of returned html to make it more css friendly
