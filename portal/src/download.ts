/** Hand a Blob to the browser as a file download. Its own module (rather
 * than living in ReportViewer.tsx) so pages that only need to download --
 * RunReportPage's xlsx path -- don't pull ReportViewer, and pdf.js with it,
 * into the main bundle. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  // Deferred, not immediate -- revoking synchronously can race the
  // browser's own click-triggered download handoff in some engines.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
