# import os
# import nltk
# import ingestion_daemon.config as cfg
# required_env_vars = {
#     "local": ["ZMQ_SUBSCRIPTION"],
#     "gcp": ["GCLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"],
# }
# def _init():
#     platform = os.environ.get("PLATFORM", "gcp")
#     for k in required_env_vars[platform]:
#         if k not in os.environ:
#             raise Exception(
#                 f"required environment variable {k} not set, exiting application",
#             )
#     env = os.environ.get("ENV", "dev")
#     cfg.set_config("ENV", env)
#     cfg.set_config("PLATFORM", platform)
#     if platform == "gcp" and cfg.get_config_as_bool("ENABLE_GCP_LOGGING", True):
#         setup_gcp_logging()
# def setup_gcp_logging():
#     import google.cloud.logging
#     client = google.cloud.logging.Client()
#     client.setup_logging(cfg.log_level())
# _init()
