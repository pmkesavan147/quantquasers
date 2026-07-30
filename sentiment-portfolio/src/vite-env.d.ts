/// <reference types="vite/client" />

// Typed so a missing VITE_API_BASE is a compile-time conversation rather than a
// runtime `undefined` in a fetch URL.
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
