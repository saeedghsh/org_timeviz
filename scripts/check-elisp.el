;;; check-elisp.el --- Byte-compile files, failing on any warning -*- lexical-binding: t; -*-

;; Usage: emacs --batch -Q --load scripts/check-elisp.el FILE...
;;
;; Byte-compiling evaluates `require' forms but none of the other top-level
;; forms, so the exporters' batch entry points do not run and no Org file is
;; read.  The compiled files go to a temporary directory that is removed
;; afterwards, so nothing is written next to the sources.

(require 'bytecomp)

(let* ((files command-line-args-left)
       (output-dir (make-temp-file "org-timeviz-elc-" t))
       (byte-compile-dest-file-function
        (lambda (source)
          (expand-file-name (concat (file-name-nondirectory source) "c") output-dir)))
       (byte-compile-error-on-warn t)
       (failed (null files)))
  ;; Keep Emacs from visiting the files once this script returns.
  (setq command-line-args-left nil)
  (unwind-protect
      (dolist (file files)
        (unless (eq (byte-compile-file file) t)
          (setq failed t)))
    (delete-directory output-dir t))
  (kill-emacs (if failed 1 0)))

;;; check-elisp.el ends here
