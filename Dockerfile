FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir Flask gunicorn
COPY app app
ENV DB_PATH=/srv/data/data.db
RUN mkdir -p /srv/data
EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "app.main:app"]
