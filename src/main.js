import "./styles.css";
import {
  channels,
  footerContact,
  featureStory,
  launchItems,
  newsCards,
  signalStrip,
  translations,
  workflowSteps
} from "./content/site-data.js";

let currentLanguage = "en";

const copyNodes = document.querySelectorAll("[data-copy]");
const langButtons = document.querySelectorAll("[data-lang]");
const featureStoryRoot = document.querySelector("#feature-story");
const newsGridRoot = document.querySelector("#news-grid");
const workflowRoot = document.querySelector("#workflow-list");
const channelRoot = document.querySelector("#channel-grid");
const signalStripRoot = document.querySelector("#signal-strip");
const launchGridRoot = document.querySelector("#launch-grid");
const footerContactRoot = document.querySelector("#footer-contact");

function renderCopy() {
  const dictionary = translations[currentLanguage];
  copyNodes.forEach((node) => {
    const key = node.dataset.copy;
    if (dictionary[key]) {
      node.textContent = dictionary[key];
    }
  });
  document.documentElement.lang = currentLanguage;
}

function renderFeatureStory() {
  const story = featureStory[currentLanguage];
  const dictionary = translations[currentLanguage];

  featureStoryRoot.innerHTML = `
    <article class="feature-card">
      <p class="card-label">${dictionary.featureLabel}</p>
      <span class="pill">${story.category}</span>
      <h3>${story.title}</h3>
      <p>${story.summary}</p>
    </article>
  `;
}

function renderNewsGrid() {
  newsGridRoot.innerHTML = newsCards
    .map((card) => {
      const item = card[currentLanguage];
      return `
        <article class="news-card accent-${card.accent}">
          <p class="card-label">${item.category}</p>
          <h3>${item.title}</h3>
          <p>${item.summary}</p>
        </article>
      `;
    })
    .join("");
}

function renderWorkflow() {
  workflowRoot.innerHTML = workflowSteps[currentLanguage]
    .map((step) => `<li>${step}</li>`)
    .join("");
}

function renderSignalStrip() {
  signalStripRoot.innerHTML = signalStrip[currentLanguage]
    .map((item) => `<span class="signal-pill">${item}</span>`)
    .join("");
}

function renderChannels() {
  const dictionary = translations[currentLanguage];

  channelRoot.innerHTML = channels
    .map((channel) => {
      const item = channel.labels[currentLanguage];
      const statusLabel =
        channel.status === "ready" ? dictionary.channelStatusReady : dictionary.channelStatusPending;
      return `
        <article class="channel-card">
          <div class="channel-header">
            <h3>${item.name}</h3>
            <span class="status-badge status-${channel.status}">${statusLabel}</span>
          </div>
          <p>${item.summary}</p>
          <p class="channel-handle">${channel.handle}</p>
          ${
            channel.url
              ? `<a class="channel-link" href="${channel.url}" target="_blank" rel="noreferrer">Open</a>`
              : `<span class="channel-link channel-link-disabled">Pending setup</span>`
          }
        </article>
      `;
    })
    .join("");
}

function renderLaunchGrid() {
  launchGridRoot.innerHTML = launchItems
    .map((item) => {
      const copy = item[currentLanguage];
      const dictionary = translations[currentLanguage];
      const statusLabel =
        item.status === "ready" ? dictionary.channelStatusReady : dictionary.channelStatusPending;

      return `
        <article class="launch-card">
          <div class="channel-header">
            <h3>${copy.title}</h3>
            <span class="status-badge status-${item.status}">${statusLabel}</span>
          </div>
          <p>${copy.summary}</p>
        </article>
      `;
    })
    .join("");
}

function renderFooterContact() {
  footerContactRoot.innerHTML = `
    <p class="footer-note">${footerContact.note[currentLanguage]}</p>
    ${
      footerContact.active
        ? `<a class="footer-link" href="mailto:${footerContact.email}">${footerContact.email}</a>`
        : `<span class="footer-link footer-link-muted">${footerContact.email}</span>`
    }
    <span class="footer-note">${footerContact.location}</span>
  `;
}

function renderPage() {
  renderCopy();
  renderSignalStrip();
  renderFeatureStory();
  renderNewsGrid();
  renderWorkflow();
  renderChannels();
  renderLaunchGrid();
  renderFooterContact();
}

langButtons.forEach((button) => {
  button.addEventListener("click", () => {
    currentLanguage = button.dataset.lang;
    langButtons.forEach((item) => item.classList.toggle("is-active", item === button));
    renderPage();
  });
});

renderPage();
