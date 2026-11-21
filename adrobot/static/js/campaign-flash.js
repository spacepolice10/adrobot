const campaignFlash = document.querySelector(".campaign-flash");
window.setTimeout(() => campaignFlash.remove(), 6000);
window.addEventListener("pagehide", () => campaignFlash.remove(), { once: true });
