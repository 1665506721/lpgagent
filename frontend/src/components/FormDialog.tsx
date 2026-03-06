import { useEffect, useMemo, useState } from "react";
import type { FormPayload } from "../lib/api";
import { buildFields, normalizePayload, resolvePlaceholder } from "../lib/schemaForm";

type FormDialogProps = {
  open: boolean;
  form: FormPayload | null;
  onClose: () => void;
  onSubmit: (formId: string, payload: Record<string, unknown>) => Promise<void>;
};

const LONG_TEXT_FIELDS = new Set(["description", "issue_description", "notes"]);
const FULL_WIDTH_FIELDS = new Set(["description", "issue_description", "notes", "address", "new_address"]);
const ORDER_SERVICE_TAGS = [
  "回收空瓶",
  "加急配送",
  "上门安检",
  "更换软管咨询",
  "报警器咨询",
  "热水器通风检查",
  "钢瓶检测提醒"
];

export default function FormDialog({ open, form, onClose, onSubmit }: FormDialogProps) {
  const fields = useMemo(() => buildFields(form?.schema), [form]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (form?.prefill) {
      setValues(form.prefill);
    } else {
      setValues({});
    }
    setErrors({});
  }, [form]);

  if (!open || !form) {
    return null;
  }

  const handleChange = (name: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => ({ ...prev, [name]: "" }));
  };

  const appendNote = (tag: string) => {
    setValues((prev) => {
      const current = typeof prev.notes === "string" ? prev.notes.trim() : "";
      if (!current) {
        return { ...prev, notes: tag };
      }
      if (current.includes(tag)) {
        return prev;
      }
      return { ...prev, notes: `${current}、${tag}` };
    });
  };

  const handleSubmit = async () => {
    const requiredErrors: Record<string, string> = {};
    fields.forEach((field) => {
      if (!field.required) {
        return;
      }
      const value = values[field.name];
      if (value === undefined || value === null || value === "") {
        requiredErrors[field.name] = "必填项";
      }
    });
    setErrors(requiredErrors);
    if (Object.keys(requiredErrors).length > 0) {
      return;
    }
    setSubmitting(true);
    try {
      const payload = normalizePayload(fields, values);
      await onSubmit(form.form_id, payload);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">{form.title}</h2>
            <p className="mt-2 text-sm text-slate-500">{form.description}</p>
          </div>
          <button
            type="button"
            className="rounded-full px-3 py-1 text-sm text-slate-500 hover:bg-slate-100"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto px-6 py-5 scrollbar-thin">
          {form.form_id === "order_create_v1" ? (
            <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <div className="text-sm font-medium text-amber-900">可选服务与物品</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {ORDER_SERVICE_TAGS.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => appendNote(tag)}
                    className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs text-amber-800 hover:border-amber-300"
                  >
                    {tag}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-amber-700">点击后会自动填入备注，方便下单说明。</p>
            </div>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            {fields.map((field) => {
              const value = values[field.name];
              const error = errors[field.name];
              const isLongText = LONG_TEXT_FIELDS.has(field.name);
              const isFullWidth = FULL_WIDTH_FIELDS.has(field.name);
              return (
                <div
                  key={field.name}
                  className={`flex flex-col gap-2 ${isFullWidth ? "md:col-span-2" : "md:col-span-1"}`}
                >
                  <label className="text-sm font-medium text-slate-700">
                    {field.label}
                    {field.required ? <span className="text-rose-500"> *</span> : null}
                  </label>
                  {field.type === "enum" ? (
                    <select
                      value={String(value ?? "")}
                      onChange={(event) => handleChange(field.name, event.target.value)}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-slate-400 focus:outline-none"
                    >
                      <option value="">请选择</option>
                      {field.options?.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : field.type === "boolean" ? (
                    <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(event) => handleChange(field.name, event.target.checked)}
                        className="h-4 w-4 rounded border-slate-300 text-slate-900"
                      />
                      {Boolean(value) ? "是" : "否"}
                    </label>
                  ) : isLongText ? (
                    <textarea
                      rows={4}
                      value={value === undefined || value === null ? "" : String(value)}
                      placeholder={resolvePlaceholder(field.name)}
                      onChange={(event) => handleChange(field.name, event.target.value)}
                      className="resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-slate-400 focus:outline-none"
                    />
                  ) : (
                    <input
                      type={field.type === "integer" || field.type === "number" ? "number" : "text"}
                      value={value === undefined || value === null ? "" : String(value)}
                      placeholder={resolvePlaceholder(field.name)}
                      onChange={(event) => handleChange(field.name, event.target.value)}
                      className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-slate-400 focus:outline-none"
                    />
                  )}
                  {error ? <span className="text-xs text-rose-500">{error}</span> : null}
                </div>
              );
            })}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-slate-200 px-6 py-4">
          <div className="text-xs text-slate-500">
            {form.confirm_required ? "提交后将进入确认流程" : "请核对信息后提交"}
          </div>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {submitting ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : null}
            {form.cta_label || "提交"}
          </button>
        </div>
      </div>
    </div>
  );
}
