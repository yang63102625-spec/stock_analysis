import type React from 'react';

export interface DeleteSessionDialogProps {
  onConfirm: () => void;
  onCancel: () => void;
}

export const DeleteSessionDialog: React.FC<DeleteSessionDialogProps> = ({ onConfirm, onCancel }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onCancel}>
    <div
      className="bg-elevated border border-border rounded-xl p-6 max-w-sm mx-4 shadow-2xl"
      onClick={(e) => e.stopPropagation()}
    >
      <h3 className="text-primary font-medium mb-2">删除对话</h3>
      <p className="text-sm text-secondary mb-5">
        删除后，该对话将不可恢复，确认删除吗？
      </p>
      <div className="flex justify-end gap-3">
        <button
          onClick={onCancel}
          className="px-4 py-1.5 rounded-lg text-sm text-secondary hover:text-primary hover:bg-surface-hover border border-border transition-colors"
        >
          取消
        </button>
        <button
          onClick={onConfirm}
          className="px-4 py-1.5 rounded-lg text-sm text-white bg-red-500/80 hover:bg-red-500 transition-colors"
        >
          删除
        </button>
      </div>
    </div>
  </div>
);

export default DeleteSessionDialog;
