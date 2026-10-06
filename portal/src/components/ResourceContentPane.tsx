import { useDraggable } from "@dnd-kit/core";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { UploadIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import type { Folder, ImageResource, ReportMeta } from "../types";

function ReportCard({ report }: { report: ReportMeta }) {
  const draggable = useDraggable({ id: `drag-report:${report.report_id}`, data: { kind: "report", id: report.report_id } });
  return (
    <article
      ref={draggable.setNodeRef}
      {...draggable.listeners}
      {...draggable.attributes}
      className="card resource-card"
      style={{ opacity: draggable.isDragging ? 0.4 : 1, cursor: "grab" }}
    >
      <div className="card-top">
        <h3 className="card-name">{report.name}</h3>
        <span className={`badge badge-${report.template_ext}`}>{report.template_ext}</span>
      </div>
      {/* Always rendered, even blank -- .card-desc reserves two lines'
          worth of height either way, so a card with no description is
          never shorter than one that has it (matters most in a CSS
          Grid row that's otherwise alone, with nothing else to stretch
          against -- see styles/pages.css's own note on .card-desc). */}
      <p className="card-desc">{report.description}</p>
      <div className="card-meta">
        <span>Report</span>
        <span>{new Date(report.updated_at).toLocaleDateString()}</span>
      </div>
    </article>
  );
}

function ImageThumbnail({ image }: { image: ImageResource }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    api.images
      .fileBlob(image.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [image.id]);

  return (
    <div className="resource-thumb">
      {src ? <img src={src} alt="" /> : <span className="muted">…</span>}
    </div>
  );
}

function ImageCard({ image, canManage, onDelete }: { image: ImageResource; canManage: boolean; onDelete: () => void }) {
  const draggable = useDraggable({ id: `drag-image:${image.id}`, data: { kind: "image", id: image.id } });
  return (
    <article
      ref={draggable.setNodeRef}
      {...draggable.listeners}
      {...draggable.attributes}
      className="card resource-card"
      style={{ opacity: draggable.isDragging ? 0.4 : 1, cursor: "grab" }}
    >
      <ImageThumbnail image={image} />
      <div className="card-top">
        <h3 className="card-name">{image.name}</h3>
        <span className="badge badge-docx">{image.file_ext}</span>
      </div>
      <div className="card-meta">
        <span>
          {image.width_px}×{image.height_px}px
        </span>
        {canManage && (
          <button
            type="button"
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            delete
          </button>
        )}
      </div>
    </article>
  );
}

export default function ResourceContentPane({
  folder,
  reports,
  images,
  canManage,
  orgId,
  onImageUploaded,
  onImageDeleted,
}: {
  folder: Folder | null;
  reports: ReportMeta[];
  images: ImageResource[];
  canManage: boolean;
  orgId: string;
  onImageUploaded: (image: ImageResource) => void;
  onImageDeleted: (id: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const image = await api.images.upload(file.name, orgId, folder?.id ?? null, file);
      onImageUploaded(image);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload image");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await api.images.delete(id);
      onImageDeleted(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete image");
    }
  }

  const empty = reports.length === 0 && images.length === 0;

  return (
    <div className="resource-content">
      <div className="resource-content-header">
        <div>
          <h2 className="resource-content-title">{folder ? folder.name : "All Resources"}</h2>
          {folder?.description && <p className="muted" style={{ margin: "2px 0 0" }}>{folder.description}</p>}
        </div>
        {canManage && (
          <>
            <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleFileChange} />
            <button type="button" className="btn btn-sm" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
              {uploading ? <span className="spinner" /> : <UploadIcon />}
              Upload image
            </button>
          </>
        )}
      </div>

      {error && <p className="alert alert-error">{error}</p>}

      {empty ? (
        <div className="empty-state">
          <p>Nothing here yet.</p>
          <p className="muted" style={{ maxWidth: 380, margin: "6px auto 0" }}>
            Drag a report or image from another folder into this one from the tree on the left, or upload an image directly.
          </p>
        </div>
      ) : (
        <div className="card-grid">
          {reports.map((r, i) => (
            <div key={r.report_id} style={{ "--i": i } as CSSProperties}>
              <ReportCard report={r} />
            </div>
          ))}
          {images.map((img, i) => (
            <div key={img.id} style={{ "--i": reports.length + i } as CSSProperties}>
              <ImageCard image={img} canManage={canManage} onDelete={() => handleDelete(img.id)} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
