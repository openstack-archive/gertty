FROM pydev
COPY . /gertty
RUN pip install -e /gertty
RUN useradd developer
USER developer
VOLUME /home/developer
CMD gertty
