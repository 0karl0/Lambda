(function () {
  const config = window.APP_CONFIG;
  if (!config) {
    throw new Error("APP_CONFIG is required. Copy config.example.js to config.js and update it.");
  }

  AWS.config.update({ region: config.awsRegion });
  AWS.config.credentials = new AWS.CognitoIdentityCredentials({
    IdentityPoolId: config.identityPoolId
  });

  const s3Upload = new AWS.S3({ params: { Bucket: config.uploadBucket } });
  const form = document.getElementById("upload-form");
  const statusEl = document.getElementById("status");
  const progressEl = document.querySelector(".progress");
  const progressBar = document.getElementById("progress-bar");
  const resultsSection = document.getElementById("results");
  const resultImage = document.getElementById("result-image");
  const thumbnailImage = document.getElementById("thumbnail-image");

  function resetUI() {
    statusEl.textContent = "";
    progressEl.hidden = true;
    progressBar.style.width = "0%";
    resultsSection.hidden = true;
  }

  function setStatus(message) {
    statusEl.textContent = message;
  }

  async function uploadFile(file) {
    return new Promise((resolve, reject) => {
      const upload = s3Upload.upload({
        Key: `${Date.now()}_${file.name}`,
        Body: file,
        ContentType: file.type
      });

      progressEl.hidden = false;
      upload.on("httpUploadProgress", (evt) => {
        if (!evt.total) return;
        const percent = Math.round((evt.loaded / evt.total) * 100);
        progressBar.style.width = `${percent}%`;
      });

      upload.send((err, data) => {
        if (err) {
          reject(err);
        } else {
          resolve(data.Key);
        }
      });
    });
  }

  function buildPublicUrl(bucket, key) {
    if (config.publicBaseUrl) {
      return `${config.publicBaseUrl.replace(/\/$/, "")}/${key}`;
    }

    return `https://${bucket}.s3.${config.awsRegion}.amazonaws.com/${encodeURIComponent(key).replace(/%2F/g, "/")}`;
  }

  async function pollForResults(originalKey) {
    const outputKey = `${config.processedPrefix}${originalKey}`;
    const thumbnailKey = `${config.thumbnailPrefix}${originalKey}`;
    const outputUrl = buildPublicUrl(config.outputBucket, outputKey);
    const thumbnailUrl = buildPublicUrl(config.outputBucket, thumbnailKey);

    const exists = async (url) => {
      const response = await fetch(url, { method: "HEAD" });
      return response.ok;
    };

    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    setStatus("Waiting for SageMaker to finish processing...");

    while (true) {
      try {
        const [outputReady, thumbnailReady] = await Promise.all([
          exists(outputUrl),
          exists(thumbnailUrl)
        ]);

        if (outputReady && thumbnailReady) {
          return { outputUrl, thumbnailUrl };
        }
      } catch (error) {
        console.error("Polling error", error);
      }

      await wait(config.pollingIntervalMs || 5000);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    resetUI();

    const file = document.getElementById("image-input").files[0];
    if (!file) {
      setStatus("Please choose an image first.");
      return;
    }

    try {
      setStatus("Uploading to S3...");
      const objectKey = await uploadFile(file);
      setStatus("Image uploaded. Processing has started.");

      const { outputUrl, thumbnailUrl } = await pollForResults(objectKey);

      resultImage.src = outputUrl;
      thumbnailImage.src = thumbnailUrl;
      resultsSection.hidden = false;
      setStatus("Processing complete. Displaying results.");
    } catch (error) {
      console.error(error);
      setStatus(`Something went wrong: ${error.message || error}`);
    } finally {
      progressEl.hidden = true;
      progressBar.style.width = "0%";
    }
  });
})();
