import { useState, useCallback } from 'react';

const ARCHIVE_EXTS = ['.tar.gz', '.tgz', '.zip'];

function isArchive(name) {
  return ARCHIVE_EXTS.some((ext) => name.toLowerCase().endsWith(ext));
}

export default function FileDropZone({ onUpload, disabled }) {
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = useCallback(
    (files) => {
      if (!files.length || disabled) return;
      const file = files[0];
      const type = isArchive(file.name) ? 'codebase' : 'document';
      onUpload(file, type);
    },
    [onUpload, disabled]
  );

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`border-2 border-dashed rounded-lg p-10 text-center transition-colors ${
        dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white'
      } ${disabled ? 'opacity-50 pointer-events-none' : 'cursor-pointer'}`}
      onClick={() => {
        if (disabled) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.onchange = (e) => handleFiles(e.target.files);
        input.click();
      }}
    >
      <div className="text-gray-500">
        <p className="text-lg font-medium">Drop files here or click to browse</p>
        <p className="text-sm mt-1">
          Documents: PDF, MD, TXT, RST, HTML &mdash; Archives: tar.gz, zip (codebase)
        </p>
      </div>
    </div>
  );
}
