"use client";

import { useEffect } from "react";

import { BRAND } from "@/brand/brand";

// Runtime rebrand of the product name in user-visible copy.
//
// Dograh's UI has no i18n layer, so its ~30 prose mentions of "Dograh" are
// hardcoded across upstream files. Rewriting them in place would conflict on
// every upstream merge; instead this observer swaps the whole word at display
// time. Identifiers such as `window.DograhWidget` are untouched (no word
// boundary), as is anything inside code samples or form fields.

const PATTERN = /\bDograh\b/g;
const SKIP_TAGS = new Set(["CODE", "PRE", "KBD", "SAMP", "SCRIPT", "STYLE", "TEXTAREA", "INPUT", "NOSCRIPT"]);
const ATTRIBUTES = ["title", "placeholder", "aria-label", "alt"];

function isSkipped(node: Node | null): boolean {
  for (let el = node instanceof Element ? node : node?.parentElement; el; el = el.parentElement) {
    if (SKIP_TAGS.has(el.tagName) || (el instanceof HTMLElement && el.isContentEditable) || el.hasAttribute("data-no-rebrand")) {
      return true;
    }
  }
  return false;
}

function rebrandText(node: Text) {
  const value = node.nodeValue;
  if (!value || !value.includes("Dograh") || isSkipped(node)) return;
  const next = value.replace(PATTERN, BRAND.productName);
  if (next !== value) node.nodeValue = next;
}

function rebrandAttributes(el: Element) {
  if (isSkipped(el)) return;
  for (const name of ATTRIBUTES) {
    const value = el.getAttribute(name);
    if (value && value.includes("Dograh")) {
      el.setAttribute(name, value.replace(PATTERN, BRAND.productName));
    }
  }
}

function rebrandTree(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    rebrandText(root as Text);
    return;
  }
  if (!(root instanceof Element)) return;
  rebrandAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) rebrandText(node as Text);
    else rebrandAttributes(node as Element);
  }
}

export function BrandRuntime() {
  useEffect(() => {
    if (!BRAND.enabled) return;

    const rebrandTitle = () => {
      if (document.title.includes("Dograh")) {
        document.title = document.title.replace(PATTERN, BRAND.productName);
      }
    };

    rebrandTree(document.body);
    rebrandTitle();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          rebrandText(mutation.target as Text);
        } else if (mutation.type === "attributes") {
          rebrandAttributes(mutation.target as Element);
        } else {
          mutation.addedNodes.forEach(rebrandTree);
        }
      }
      rebrandTitle();
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRIBUTES,
    });
    return () => observer.disconnect();
  }, []);

  return null;
}
