FROM public.ecr.aws/sagemaker/sagemaker-inference:2.1-cpu-py310

ENV PYTHONUNBUFFERED=1 \
    MODEL_ARTIFACT_PATH=/opt/ml/model

COPY requirements.txt /opt/program/requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /opt/program/requirements.txt

COPY serve.py /opt/program/serve.py

ENV PYTHONPATH=/opt/program

ENTRYPOINT ["python", "/opt/program/serve.py"]
