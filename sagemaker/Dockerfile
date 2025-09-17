#FROM public.ecr.aws/sagemaker/sagemaker-inference:2.1-cpu-py310
FROM public.ecr.aws/sagemaker/sagemaker-distribution:latest-cpu
#USER $ROOT
#RUN apt-get install -y vim
#USER $MAMBA_USER
#RUN micromamba install sagemaker-inference --freeze-installed --yes --channel conda-forge --name base
ENV PYTHONUNBUFFERED=1 \
    MODEL_ARTIFACT_PATH=/opt/ml/model

COPY requirements.txt /opt/program/requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /opt/program/requirements.txt

COPY serve.py /opt/program/serve.py

ENV PYTHONPATH=/opt/program

ENTRYPOINT ["python", "/opt/program/serve.py"]
