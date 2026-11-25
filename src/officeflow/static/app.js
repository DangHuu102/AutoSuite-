(() => {
  "use strict";

  const MAX_FILES = 20;
  const MAX_SINGLE_BYTES = 100 * 1024 * 1024;
  const MAX_BATCH_BYTES = 500 * 1024 * 1024;

  const OFFICE_EXTS = new Set([".docx", ".xlsx", ".pptx"]);
  const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"]);
  const REJECTED_LEGACY = new Set([".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm"]);
  const REJECTED_IMAGES = new Set([".gif", ".heic"]);

  const MIME_PDF = "application/pdf";
  const MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  const state = {
    mode: "auto", // auto | pdf2word | office2pdf | ocr2pdf | mergeimg
    pdfRouteChoice: "docx", // docx | pdf
    imgMergeChoice: true,
    ocrLanguage: "vie",
    mergedPdfName: "Anh-gop.pdf",
    files: [],
    activeXhr: null,
    activeSse: null,
    pollTimer: null,
    finishTimer: null,
    currentJob: null,
    previewLoadedFor: "",
    aiModelsLoaded: false,
    patchDebounce: null,
    user: null,
    authChecked: false,
  };

  const $ = (id) => document.getElementById(id);

  const els = {
    dragOverlay: $("drag-overlay"),
    chkAutostart: $("chk-autostart"),
    step1: $("step-pill-1"),
    step2: $("step-pill-2"),
    step3: $("step-pill-3"),
    toolBarWrap: $("tool-bar-wrap"),
    toast: $("global-toast"),
    viewUpload: $("view-upload"),
    viewConverting: $("view-converting"),
    viewDownload: $("view-download"),
    viewAuth: $("view-auth"),
    viewAccount: $("view-account"),
    viewAdmin: $("view-admin"),
    authGuestControls: $("auth-guest-controls"),
    authUserControls: $("auth-user-controls"),
    navUserAvatar: $("nav-user-avatar"),
    navUserName: $("nav-user-name"),
    navUserRole: $("nav-user-role"),
    navBtnAdmin: $("nav-btn-admin"),
    navBtnLogout: $("nav-btn-logout"),
    guestHistoryNudge: $("guest-history-nudge"),
    tabAuthLogin: $("tab-auth-login"),
    tabAuthSignup: $("tab-auth-signup"),
    authErrorBox: $("auth-error-box"),
    formLogin: $("form-login"),
    loginIdentifier: $("login-identifier"),
    loginPassword: $("login-password"),
    loginRemember: $("login-remember"),
    btnSubmitLogin: $("btn-submit-login"),
    errLoginIdentifier: $("err-login-identifier"),
    errLoginPassword: $("err-login-password"),
    formSignup: $("form-signup"),
    signupUsername: $("signup-username"),
    signupEmail: $("signup-email"),
    signupPassword: $("signup-password"),
    signupConfirm: $("signup-confirm"),
    btnSubmitSignup: $("btn-submit-signup"),
    errSignupUsername: $("err-signup-username"),
    errSignupEmail: $("err-signup-email"),
    errSignupPassword: $("err-signup-password"),
    errSignupConfirm: $("err-signup-confirm"),
    accountAvatarLg: $("account-avatar-lg"),
    accountUsername: $("account-username"),
    accountRoleBadge: $("account-role-badge"),
    accountEmail: $("account-email"),
    accountCreated: $("account-created"),
    btnAccountLogout: $("btn-account-logout"),
    btnRefreshHistory: $("btn-refresh-history"),
    historyEmpty: $("history-empty"),
    historyList: $("history-list"),
    formChangePw: $("form-change-pw"),
    pwCurrent: $("pw-current"),
    pwNew: $("pw-new"),
    pwConfirm: $("pw-confirm"),
    pwChangeMsg: $("pw-change-msg"),
    btnSavePw: $("btn-save-pw"),
    adminForbiddenCard: $("admin-forbidden-card"),
    adminPanelCard: $("admin-panel-card"),
    btnRefreshAdmin: $("btn-refresh-admin"),
    adminUsersTbody: $("admin-users-tbody"),
    heroTitle: $("hero-title"),
    heroSub: $("hero-subtitle"),
    dropzone: $("dropzone"),
    dropzoneHeadline: $("dropzone-headline"),
    dropzoneHint: $("dropzone-hint"),
    fileInput: $("file-input"),
    btnPickFiles: $("btn-pick-files"),
    stagedPanel: $("staged-panel"),
    stagedTotalSize: $("staged-total-size"),
    autoRouteChip: $("auto-route-chip"),
    btnAddMore: $("btn-add-more"),
    btnClearFiles: $("btn-clear-files"),
    validationBanner: $("validation-banner"),
    smartSwitchBanner: $("smart-switch-banner"),
    routeOptionsBar: $("route-options-bar"),
    optPdfRoute: $("opt-pdf-route"),
    optImageMerge: $("opt-image-merge"),
    optMergedNameWrap: $("opt-merged-name-wrap"),
    inputMergedName: $("input-merged-name"),
    optOcrLang: $("opt-ocr-lang"),
    selectOcrLang: $("select-ocr-lang"),
    stagedFileList: $("staged-file-list"),
    btnStartConvert: $("btn-start-convert"),
    progressPhase: $("progress-phase-label"),
    progressPct: $("progress-percent"),
    progressHeadline: $("progress-headline"),
    progressSub: $("progress-subtext"),
    progressOuter: $("progress-bar-outer"),
    progressFill: $("progress-bar-fill"),
    progressCounter: $("progress-counter"),
    btnCancelJob: $("btn-cancel-job"),
    downloadIssues: $("download-issues-box"),
    emptyCard: $("download-empty-card"),
    btnRetryEmpty: $("btn-retry-from-empty"),
    singleCard: $("single-download-card"),
    singleElapsed: $("single-elapsed"),
    singleExtBadge: $("single-ext-badge"),
    singleNameStem: $("single-name-stem"),
    singleExtLocked: $("single-ext-locked"),
    singleMetaChips: $("single-meta-chips"),
    btnSingleDownload: $("btn-single-download"),
    btnSingleSaveAs: $("btn-single-save-as"),
    singleSaveFeedback: $("single-save-feedback"),
    batchCard: $("batch-download-card"),
    batchElapsed: $("batch-elapsed"),
    batchTitle: $("batch-summary-title"),
    batchSub: $("batch-summary-sub"),
    btnBatchZip: $("btn-batch-zip"),
    btnBatchFolder: $("btn-batch-folder-picker"),
    batchSaveFeedback: $("batch-save-feedback"),
    batchList: $("batch-output-list"),
    optionalDrawers: $("optional-drawers"),
    drawerPreview: $("drawer-preview"),
    previewSelectorRow: $("preview-selector-row"),
    selectPreviewOutput: $("select-preview-output"),
    previewContainer: $("preview-container"),
    drawerAi: $("drawer-ai"),
    aiProvider: $("ai-provider"),
    aiOllamaWrap: $("ai-ollama-model-wrap"),
    aiOllamaModel: $("ai-ollama-model"),
    btnRefreshOllama: $("btn-refresh-ollama"),
    aiOpenaiWrap: $("ai-openai-model-wrap"),
    aiOpenaiModel: $("ai-openai-model"),
    aiConsentWrap: $("ai-cloud-consent-wrap"),
    aiConsent: $("ai-cloud-consent"),
    aiPrompt: $("ai-filter-prompt"),
    btnRunAi: $("btn-run-ai"),
    btnApplyAiNames: $("btn-apply-ai-names"),
    aiResultsList: $("ai-results-list"),
    footerBar: $("download-footer-bar"),
    btnConvertAnother: $("btn-convert-another"),
    linkReportCsv: $("link-report-csv"),
    linkReportJson: $("link-report-json"),
    brandHome: $("brand-home"),
  };

  function getExt(name) {
    const idx = (name || "").lastIndexOf(".");
    return idx >= 0 ? name.slice(idx).toLowerCase() : "";
  }

  function stripExt(name, ext) {
    if ((name || "").toLowerCase().endsWith(ext.toLowerCase())) {
      return name.slice(0, -ext.length);
    }
    const idx = (name || "").lastIndexOf(".");
    return idx > 0 ? name.slice(0, idx) : name || "tai-lieu";
  }

  function cleanStemClient(stem) {
    const cleaned = (stem || "")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .trim()
      .replace(/[. ]+$/g, "");
    return cleaned || "tai-lieu";
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function showToast(msg, isError = false) {
    if (!msg) {
      els.toast.hidden = true;
      return;
    }
    els.toast.textContent = msg;
    els.toast.className = isError ? "toast error" : "toast";
    els.toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      els.toast.hidden = true;
    }, 5000);
  }

  function setStepIndicator(step) {
    [els.step1, els.step2, els.step3].forEach((el, idx) => {
      const n = idx + 1;
      el.classList.remove("active", "done");
      if (n < step) el.classList.add("done");
      else if (n === step) el.classList.add("active");
    });
  }

  function navigateView(viewName, pushHash = true, jobId = "") {
    els.viewUpload.hidden = viewName !== "upload";
    els.viewConverting.hidden = viewName !== "converting";
    els.viewDownload.hidden = viewName !== "download";
    els.viewAuth.hidden = viewName !== "login" && viewName !== "signup";
    els.viewAccount.hidden = viewName !== "account";
    els.viewAdmin.hidden = viewName !== "admin";
    els.toolBarWrap.hidden = viewName !== "upload";

    if (viewName === "upload") {
      setStepIndicator(1);
      if (pushHash && location.hash !== "#upload" && location.hash !== "") {
        history.pushState({ view: "upload" }, "", "#upload");
      }
    } else if (viewName === "converting") {
      setStepIndicator(2);
      if (pushHash) {
        history.pushState({ view: "converting" }, "", "#converting");
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (viewName === "download") {
      setStepIndicator(3);
      const hashTarget = jobId ? `#download/${jobId}` : "#download";
      if (pushHash && location.hash !== hashTarget) {
        history.replaceState({ view: "download", jobId }, "", hashTarget);
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (viewName === "login" || viewName === "signup") {
      switchAuthTab(viewName);
      const target = `#${viewName}`;
      if (pushHash && location.hash !== target) {
        history.pushState({ view: viewName }, "", target);
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (viewName === "account" || viewName === "admin") {
      const target = `#${viewName}`;
      if (pushHash && location.hash !== target) {
        history.pushState({ view: viewName }, "", target);
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  const MODE_META = {
    auto: {
      title: "Chuyển đổi PDF & Tài liệu thông minh",
      sub: "Thả bất kỳ tệp PDF, Word, Excel, PowerPoint hoặc Ảnh scan — hệ thống tự nhận diện công cụ phù hợp nhất và tải thẳng về trình duyệt.",
      accept: ".pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg,.tif,.tiff,.bmp",
      headline: "Kéo & thả mọi tệp vào đây để tự động nhận diện",
    },
    pdf2word: {
      title: "Chuyển PDF sang Word (.docx) — Giữ nguyên bảng biểu",
      sub: "Tái tạo cấu trúc bảng biểu, cột số liệu và văn bản tiếng Việt từ tệp PDF thường hoặc PDF scan.",
      accept: ".pdf",
      headline: "Kéo & thả tệp PDF cần chuyển sang Word (.docx)",
    },
    office2pdf: {
      title: "Chuyển Word, Excel, PowerPoint sang PDF chuẩn",
      sub: "Giữ nguyên định dạng trang in từ .docx, .xlsx, .pptx và tải xuống tức thì.",
      accept: ".docx,.xlsx,.pptx",
      headline: "Kéo & thả tệp Word, Excel hoặc PowerPoint vào đây",
    },
    ocr2pdf: {
      title: "Nhận diện chữ OCR cho Ảnh & PDF Scan",
      sub: "Tạo lớp văn bản tiếng Việt / tiếng Anh tìm kiếm và sao chép được trên PDF scan & hình ảnh.",
      accept: ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp",
      headline: "Kéo & thả ảnh chụp hoặc PDF scan cần nhận diện chữ OCR",
    },
    mergeimg: {
      title: "Ghép nhiều Ảnh Scan thành 1 tệp PDF",
      sub: "Gộp hàng loạt trang chụp (.png, .jpg, .tif, .bmp) thành một hồ sơ PDF nhiều trang kèm OCR.",
      accept: ".png,.jpg,.jpeg,.tif,.tiff,.bmp",
      headline: "Kéo & thả các ảnh cần ghép thành 1 tệp PDF",
    },
  };

  function setMode(newMode) {
    state.mode = newMode;
    document.querySelectorAll(".tool-tab").forEach((btn) => {
      const active = btn.dataset.mode === newMode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    const meta = MODE_META[newMode] || MODE_META.auto;
    els.heroTitle.textContent = meta.title;
    els.heroSub.textContent = meta.sub;
    els.fileInput.setAttribute("accept", meta.accept);
    els.dropzoneHeadline.textContent = meta.headline;
    inspectAndRenderStaging();
  }

  /**
   * 0ms Client-Side Auto-Routing & Preflight Inspection
   */
  function computeEffectiveRoute() {
    const validFiles = [];
    const errors = [];
    let pdfCount = 0;
    let officeCount = 0;
    let imageCount = 0;

    for (const f of state.files) {
      const ext = getExt(f.name);
      if (f.size === 0) {
        errors.push(`"${f.name}" là tệp rỗng (0 byte).`);
        continue;
      }
      if (f.size > MAX_SINGLE_BYTES) {
        errors.push(`"${f.name}" vượt quá giới hạn 100 MB mỗi tệp.`);
        continue;
      }
      if (REJECTED_LEGACY.has(ext)) {
        errors.push(`"${f.name}": Định dạng cũ/chứa macro (${ext}) chưa hỗ trợ. Hãy lưu sang .docx/.xlsx/.pptx.`);
        continue;
      }
      if (REJECTED_IMAGES.has(ext)) {
        errors.push(`"${f.name}": Chỉ hỗ trợ ảnh .png, .jpg, .tif, .bmp.`);
        continue;
      }
      if (ext === ".pdf") {
        pdfCount++;
        validFiles.push(f);
      } else if (OFFICE_EXTS.has(ext)) {
        officeCount++;
        validFiles.push(f);
      } else if (IMAGE_EXTS.has(ext)) {
        imageCount++;
        validFiles.push(f);
      } else {
        errors.push(`"${f.name}": Định dạng "${ext || "không rõ"}" chưa được hỗ trợ.`);
      }
    }

    let targetFormat = "pdf";
    let mergeImages = false;
    let routeLabel = "";
    let showPdfToggle = false;
    let showImgMergeToggle = false;
    let showOcrLang = false;
    let switchSuggestion = null;

    if (state.mode === "auto") {
      if (pdfCount > 0 && officeCount === 0 && imageCount === 0) {
        showPdfToggle = true;
        targetFormat = state.pdfRouteChoice;
        showOcrLang = true;
        routeLabel =
          targetFormat === "docx"
            ? "Tự động: PDF → Word (.docx) giữ bảng"
            : "Tự động: OCR PDF Scan → PDF tìm kiếm";
      } else if (officeCount > 0 && pdfCount === 0 && imageCount === 0) {
        targetFormat = "pdf";
        routeLabel = "Tự động: Tài liệu Office → PDF chuẩn";
      } else if (imageCount > 0 && pdfCount === 0 && officeCount === 0) {
        targetFormat = "pdf";
        showOcrLang = true;
        if (imageCount >= 2) {
          showImgMergeToggle = true;
          mergeImages = state.imgMergeChoice;
          routeLabel = mergeImages
            ? `Tự động: Ghép ${imageCount} ảnh → 1 PDF (OCR)`
            : `Tự động: ${imageCount} ảnh → ${imageCount} PDF riêng (OCR)`;
        } else {
          routeLabel = "Tự động: Ảnh → PDF có lớp chữ OCR";
        }
      } else if (validFiles.length > 0) {
        targetFormat = "pdf";
        showOcrLang = pdfCount > 0 || imageCount > 0;
        if (imageCount >= 2) {
          showImgMergeToggle = true;
          mergeImages = state.imgMergeChoice;
        }
        routeLabel = "Tự động: Lô hỗn hợp → Xuất sang PDF";
      }
    } else if (state.mode === "pdf2word") {
      targetFormat = "docx";
      showOcrLang = pdfCount > 0;
      routeLabel = "Chế độ: PDF → Word (.docx) giữ bảng";
      if (pdfCount === 0 && (officeCount > 0 || imageCount > 0)) {
        switchSuggestion = {
          text: "Tệp bạn vừa chọn không phải .pdf. Tự động chuyển sang chế độ Xuất PDF?",
          targetMode: "auto",
          btnLabel: "Chuyển sang Tự động nhận diện ngay",
        };
      }
    } else if (state.mode === "office2pdf") {
      targetFormat = "pdf";
      routeLabel = "Chế độ: Office → PDF";
      if (officeCount === 0 && pdfCount > 0) {
        switchSuggestion = {
          text: "Bạn vừa thả tệp PDF. Bạn có muốn chuyển PDF sang Word (.docx) giữ bảng không?",
          targetMode: "pdf2word",
          btnLabel: "Đổi sang PDF → Word",
        };
      } else if (officeCount === 0 && imageCount > 0) {
        switchSuggestion = {
          text: "Bạn vừa thả ảnh. Đổi sang chế độ Scan / Ảnh → PDF OCR?",
          targetMode: "ocr2pdf",
          btnLabel: "Đổi sang Scan / Ảnh → PDF",
        };
      }
    } else if (state.mode === "ocr2pdf") {
      targetFormat = "pdf";
      showOcrLang = true;
      if (imageCount >= 2) {
        showImgMergeToggle = true;
        mergeImages = state.imgMergeChoice;
      }
      routeLabel = "Chế độ: Scan / Ảnh → PDF OCR";
      if (imageCount === 0 && pdfCount === 0 && officeCount > 0) {
        switchSuggestion = {
          text: "Bạn vừa thả tài liệu Office. Đổi sang chế độ Office → PDF?",
          targetMode: "office2pdf",
          btnLabel: "Đổi sang Office → PDF",
        };
      }
    } else if (state.mode === "mergeimg") {
      targetFormat = "pdf";
      mergeImages = imageCount >= 1;
      showOcrLang = true;
      routeLabel = "Chế độ: Ghép Ảnh → 1 PDF";
      if (imageCount === 0 && (pdfCount > 0 || officeCount > 0)) {
        switchSuggestion = {
          text: "Chế độ Ghép Ảnh dành cho tệp hình ảnh (.png, .jpg, .tif, .bmp). Chuyển về Tự động nhận diện?",
          targetMode: "auto",
          btnLabel: "Chuyển sang Tự động nhận diện",
        };
      }
    }

    return {
      validFiles,
      errors,
      pdfCount,
      officeCount,
      imageCount,
      targetFormat,
      mergeImages,
      routeLabel,
      showPdfToggle,
      showImgMergeToggle,
      showOcrLang,
      switchSuggestion,
    };
  }

  function inspectAndRenderStaging() {
    if (state.files.length === 0) {
      els.stagedPanel.hidden = true;
      return null;
    }
    els.stagedPanel.hidden = false;

    const totalBytes = state.files.reduce((acc, f) => acc + (f.size || 0), 0);
    els.stagedTotalSize.textContent = `Tổng dung lượng: ${formatBytes(totalBytes)}`;

    const route = computeEffectiveRoute();
    els.autoRouteChip.textContent = route.routeLabel;
    els.autoRouteChip.hidden = !route.routeLabel;

    const batchErrors = [...route.errors];
    if (state.files.length > MAX_FILES) {
      batchErrors.unshift(`Mỗi lô nhận tối đa ${MAX_FILES} tệp (đang chọn ${state.files.length} tệp).`);
    }
    if (totalBytes > MAX_BATCH_BYTES) {
      batchErrors.unshift("Tổng dung lượng vượt quá 500 MB. Hãy chia nhỏ thành nhiều lô.");
    }

    if (batchErrors.length > 0) {
      els.validationBanner.textContent = batchErrors[0];
      els.validationBanner.hidden = false;
    } else {
      els.validationBanner.hidden = true;
    }

    if (route.switchSuggestion) {
      els.smartSwitchBanner.innerHTML = "";
      const span = document.createElement("span");
      span.textContent = route.switchSuggestion.text;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-pill active";
      btn.textContent = route.switchSuggestion.btnLabel;
      btn.addEventListener("click", () => setMode(route.switchSuggestion.targetMode));
      els.smartSwitchBanner.append(span, btn);
      els.smartSwitchBanner.hidden = false;
    } else {
      els.smartSwitchBanner.hidden = true;
    }

    const anyOptions = route.showPdfToggle || route.showImgMergeToggle || route.showOcrLang || route.mergeImages;
    els.routeOptionsBar.hidden = !anyOptions;
    els.optPdfRoute.hidden = !route.showPdfToggle;
    els.optImageMerge.hidden = !route.showImgMergeToggle;
    els.optMergedNameWrap.hidden = !route.mergeImages;
    els.optOcrLang.hidden = !route.showOcrLang;

    document.querySelectorAll("[data-pdf-route]").forEach((b) => {
      b.classList.toggle("active", b.dataset.pdfRoute === state.pdfRouteChoice);
    });
    document.querySelectorAll("[data-img-merge]").forEach((b) => {
      b.classList.toggle("active", (b.dataset.imgMerge === "true") === state.imgMergeChoice);
    });

    els.stagedFileList.innerHTML = "";
    state.files.forEach((file, index) => {
      const ext = getExt(file.name);
      const isBad =
        file.size === 0 ||
        file.size > MAX_SINGLE_BYTES ||
        REJECTED_LEGACY.has(ext) ||
        REJECTED_IMAGES.has(ext) ||
        (!OFFICE_EXTS.has(ext) && !IMAGE_EXTS.has(ext) && ext !== ".pdf");

      const li = document.createElement("li");
      li.className = isBad ? "file-row invalid" : "file-row";

      const left = document.createElement("div");
      left.className = "file-row-left";
      const badge = document.createElement("span");
      badge.className = "file-ext-mini";
      badge.textContent = (ext.replace(".", "") || "FILE").slice(0, 5);
      const nameSpan = document.createElement("span");
      nameSpan.className = "file-name-trunc";
      nameSpan.textContent = file.name;
      left.append(badge, nameSpan);

      const right = document.createElement("div");
      right.className = "file-row-right";
      const sizeSpan = document.createElement("span");
      sizeSpan.textContent = formatBytes(file.size || 0);
      const rmBtn = document.createElement("button");
      rmBtn.type = "button";
      rmBtn.className = "btn-remove-file";
      rmBtn.title = "Bỏ tệp này";
      rmBtn.textContent = "×";
      rmBtn.addEventListener("click", () => {
        state.files.splice(index, 1);
        inspectAndRenderStaging();
      });
      right.append(sizeSpan, rmBtn);
      li.append(left, right);
      els.stagedFileList.appendChild(li);
    });

    let usableCount = route.validFiles.length;
    if (route.targetFormat === "docx") {
      usableCount = route.pdfCount;
    } else if (state.mode === "mergeimg") {
      usableCount = route.imageCount;
    }
    const fatalInvalid =
      state.files.length > MAX_FILES || totalBytes > MAX_BATCH_BYTES || usableCount === 0;
    els.btnStartConvert.disabled = fatalInvalid;
    els.btnStartConvert.textContent =
      route.targetFormat === "docx"
        ? "🚀 Chuyển sang Word (.docx) ngay"
        : route.mergeImages
          ? "🚀 Ghép ảnh & Xuất PDF ngay"
          : "🚀 Chuyển sang PDF ngay";

    return { route, fatalInvalid };
  }

  function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    for (const f of incoming) {
      if (state.files.length >= MAX_FILES + 5) break;
      state.files.push(f);
    }
    if (els.viewUpload.hidden) {
      cleanupActiveTransport();
      state.currentJob = null;
      navigateView("upload", true);
    }
    const inspected = inspectAndRenderStaging();
    if (els.chkAutostart.checked && inspected && !inspected.fatalInvalid) {
      setTimeout(() => {
        if (!els.viewUpload.hidden && state.files.length > 0) {
          startConversion();
        }
      }, 220);
    }
  }

  function updateProgressUI(pct, phaseLabel, headline, counterText) {
    const clamped = Math.max(2, Math.min(100, Math.round(pct)));
    els.progressFill.style.transform = `scaleX(${(clamped / 100).toFixed(3)})`;
    els.progressOuter.setAttribute("aria-valuenow", String(clamped));
    els.progressPct.textContent = `${clamped}%`;
    if (phaseLabel) els.progressPhase.textContent = phaseLabel;
    if (headline) els.progressHeadline.textContent = headline;
    if (counterText !== undefined) els.progressCounter.textContent = counterText;
  }

  function cleanupActiveTransport() {
    if (state.activeXhr) {
      try { state.activeXhr.abort(); } catch (_) {}
      state.activeXhr = null;
    }
    if (state.activeSse) {
      try { state.activeSse.close(); } catch (_) {}
      state.activeSse = null;
    }
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    if (state.finishTimer) {
      clearTimeout(state.finishTimer);
      state.finishTimer = null;
    }
  }

  function startConversion() {
    const inspected = inspectAndRenderStaging();
    if (!inspected || inspected.fatalInvalid) return;
    const { route } = inspected;

    cleanupActiveTransport();
    navigateView("converting", true);

    const totalBytes = state.files.reduce((acc, f) => acc + (f.size || 0), 0);
    updateProgressUI(
      4,
      "Đang tải tệp lên…",
      route.targetFormat === "docx"
        ? "Đang chuyển PDF sang Word (.docx) giữ nguyên bảng biểu…"
        : "Đang xử lý và chuyển đổi sang PDF…",
      `0 / ${formatBytes(totalBytes)}`
    );

    const formData = new FormData();
    for (const f of state.files) {
      formData.append("files", f, f.name);
    }
    formData.append("target_format", route.targetFormat);
    formData.append("ocr_language", els.selectOcrLang.value || "vie");
    formData.append("merge_images", route.mergeImages ? "true" : "false");
    formData.append("merged_pdf_name", els.inputMergedName.value || "Anh-gop.pdf");

    const xhr = new XMLHttpRequest();
    state.activeXhr = xhr;
    xhr.open("POST", "/api/jobs", true);

    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 0) {
        const uploadRatio = ev.loaded / ev.total;
        const weighted = Math.round(uploadRatio * 26);
        updateProgressUI(
          weighted,
          uploadRatio < 1 ? "Đang tải tệp lên máy chủ…" : "Đã nhận tệp · Bắt đầu chuyển đổi…",
          null,
          `${formatBytes(ev.loaded)} / ${formatBytes(ev.total)}`
        );
      }
    };

    xhr.onload = () => {
      state.activeXhr = null;
      let payload = null;
      try { payload = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300 && payload && payload.job_id) {
        state.currentJob = payload;
        state.files = [];
        inspectAndRenderStaging();
        watchJobProgress(payload.job_id);
      } else {
        const errMsg = (payload && payload.error) || "Không thể khởi tạo lô chuyển đổi.";
        navigateView("upload", true);
        inspectAndRenderStaging();
        showToast(errMsg, true);
      }
    };

    xhr.onerror = () => {
      state.activeXhr = null;
      navigateView("upload", true);
      inspectAndRenderStaging();
      showToast("Mất kết nối tới máy chủ AutoSuite. Vui lòng thử lại.", true);
    };

    xhr.send(formData);
  }

  function watchJobProgress(jobId) {
    cleanupActiveTransport();
    updateProgressUI(28, "Đang chuyển đổi tài liệu…", null, "Đang phân tích cấu trúc trang…");

    const onJobFinished = (jobSnapshot) => {
      cleanupActiveTransport();
      state.currentJob = jobSnapshot;
      updateProgressUI(100, "Hoàn tất 100%!", "Đang mở màn hình tải xuống…", "");
      state.finishTimer = setTimeout(() => {
        state.finishTimer = null;
        renderDownloadScreen(jobSnapshot);
        navigateView("download", true, jobSnapshot.job_id);
      }, 180);
    };

    if (window.EventSource) {
      const sse = new EventSource(`/api/jobs/${jobId}/events`);
      state.activeSse = sse;

      sse.addEventListener("progress", (ev) => {
        try {
          const p = JSON.parse(ev.data);
          const mappedPct = 28 + Math.round(((p.percent || 10) / 100) * 68);
          const counter =
            p.total > 0
              ? `Đang xử lý ${p.completed}/${p.total}: ${p.current_file || ""}`
              : "Đang xử lý…";
          updateProgressUI(mappedPct, "Đang xử lý tài liệu…", null, counter);
        } catch (_) {}
      });

      sse.addEventListener("done", (ev) => {
        try {
          const snap = JSON.parse(ev.data);
          onJobFinished(snap);
        } catch (_) {
          fetchJobSnapshot(jobId, onJobFinished);
        }
      });

      sse.onerror = () => {
        sse.close();
        state.activeSse = null;
        startFallbackPolling(jobId, onJobFinished);
      };
    } else {
      startFallbackPolling(jobId, onJobFinished);
    }
  }

  function startFallbackPolling(jobId, onDone) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      const ok = await fetchJobSnapshot(jobId, (snap) => {
        if (snap.status === "review" || snap.status === "failed" || snap.status === "cancelled") {
          onDone(snap);
        } else if (snap.progress) {
          const p = snap.progress;
          const mappedPct = 28 + Math.round(((p.percent || 15) / 100) * 68);
          updateProgressUI(
            mappedPct,
            "Đang xử lý tài liệu…",
            null,
            p.total > 0 ? `Đang xử lý ${p.completed}/${p.total}: ${p.current_file || ""}` : ""
          );
        }
      });
      if (!ok) {
        cleanupActiveTransport();
        navigateView("upload", true);
        showToast("Lô chuyển đổi không còn tồn tại hoặc đã bị hủy.", true);
      }
    }, 450);
  }

  async function fetchJobSnapshot(jobId, callback) {
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
      if (!res.ok) return false;
      const data = await res.json();
      callback(data);
      return true;
    } catch (_) {
      return false;
    }
  }

  function buildSingleDownloadUrl(jobId, outputId, finalName) {
    const params = new URLSearchParams({ output_id: outputId, name: finalName });
    return `/api/jobs/${jobId}/download?${params.toString()}`;
  }

  function schedulePatchOutputs(jobId, namesMap, selectedIds) {
    clearTimeout(state.patchDebounce);
    state.patchDebounce = setTimeout(async () => {
      try {
        await fetch(`/api/jobs/${jobId}/outputs`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            names: namesMap,
            selected_ids: selectedIds,
          }),
        });
      } catch (_) {}
    }, 280);
  }

  /**
   * Stream directly from HTTP response body to disk via File System Access API (0 MB RAM buffering)
   */
  async function saveSingleWithPicker(url, suggestedName, isDocx, feedbackEl, fallbackLink) {
    if (!window.showSaveFilePicker) {
      fallbackLink.click();
      return;
    }
    const mime = isDocx ? MIME_DOCX : MIME_PDF;
    const ext = isDocx ? ".docx" : ".pdf";
    const desc = isDocx ? "Microsoft Word (.docx)" : "Tài liệu PDF (.pdf)";
    try {
      feedbackEl.hidden = false;
      feedbackEl.textContent = "Đang mở hộp thoại chọn ổ đĩa / thư mục lưu tệp…";
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: desc, accept: { [mime]: [ext] } }],
      });
      const res = await fetch(url);
      if (!res.ok || !res.body) throw new Error("Download stream error");
      const writable = await handle.createWritable();
      await res.body.pipeTo(writable);
      feedbackEl.textContent = `✓ Đã lưu thành công "${handle.name}" vào vị trí bạn chọn.`;
    } catch (err) {
      if (err && err.name === "AbortError") {
        feedbackEl.hidden = true;
        return;
      }
      feedbackEl.hidden = true;
      fallbackLink.click();
    }
  }

  async function saveBatchToFolder(jobId, items, feedbackEl, fallbackZipLink) {
    if (!window.showDirectoryPicker) {
      fallbackZipLink.click();
      return;
    }
    try {
      feedbackEl.hidden = false;
      feedbackEl.textContent = "Đang mở hộp thoại chọn thư mục đích trên máy tính…";
      const dirHandle = await window.showDirectoryPicker({ mode: "readwrite" });
      const usedNames = new Set();
      let saved = 0;
      for (const item of items) {
        const ext = getExt(item.finalName) || ".pdf";
        const baseStem = stripExt(item.finalName, ext);
        let uniqueName = `${baseStem}${ext}`;
        let serial = 1;
        while (usedNames.has(uniqueName.toLowerCase())) {
          uniqueName = `${baseStem} (${serial})${ext}`;
          serial++;
        }
        usedNames.add(uniqueName.toLowerCase());

        feedbackEl.textContent = `Đang lưu (${saved + 1}/${items.length}): ${uniqueName}…`;
        const url = buildSingleDownloadUrl(jobId, item.outputId, uniqueName);
        const res = await fetch(url);
        if (!res.ok || !res.body) throw new Error("Stream failed");
        const fileHandle = await dirHandle.getFileHandle(uniqueName, { create: true });
        const writable = await fileHandle.createWritable();
        await res.body.pipeTo(writable);
        saved++;
      }
      feedbackEl.textContent = `✓ Đã lưu trọn bộ ${saved} tệp vào thư mục "${dirHandle.name}".`;
    } catch (err) {
      if (err && err.name === "AbortError") {
        feedbackEl.hidden = true;
        return;
      }
      feedbackEl.hidden = true;
      fallbackZipLink.click();
    }
  }

  function renderDownloadScreen(job) {
    state.currentJob = job;
    state.previewLoadedFor = "";
    els.drawerPreview.open = false;
    els.drawerAi.open = false;
    els.singleSaveFeedback.hidden = true;
    els.batchSaveFeedback.hidden = true;

    const isDocx = job.target_format === "docx";
    const ext = isDocx ? ".docx" : ".pdf";

    // Render any preflight/conversion issues
    const allIssues = [];
    if (job.error_message) {
      allIssues.push({ severity: "error", message_vi: job.error_message });
    }
    for (const s of job.sources || []) {
      for (const iss of s.issues || []) {
        allIssues.push({ severity: iss.severity, message_vi: `${s.original_name}: ${iss.message_vi}` });
      }
    }
    for (const o of job.outputs || []) {
      for (const iss of o.issues || []) {
        allIssues.push({ severity: iss.severity, message_vi: iss.message_vi });
      }
    }
    els.downloadIssues.innerHTML = "";
    if (allIssues.length > 0) {
      for (const iss of allIssues) {
        const div = document.createElement("div");
        div.className = iss.severity === "warning" ? "alert alert-warn" : "alert alert-error";
        div.style.marginTop = "0";
        div.textContent = iss.message_vi;
        els.downloadIssues.appendChild(div);
      }
      els.downloadIssues.hidden = false;
    } else {
      els.downloadIssues.hidden = true;
    }

    const outputs = job.outputs || [];
    if (outputs.length === 0) {
      els.emptyCard.hidden = false;
      els.singleCard.hidden = true;
      els.batchCard.hidden = true;
      els.optionalDrawers.hidden = true;
      els.footerBar.hidden = true;
      return;
    }

    els.emptyCard.hidden = true;
    els.optionalDrawers.hidden = false;
    els.footerBar.hidden = false;
    els.drawerAi.hidden = isDocx;
    els.guestHistoryNudge.hidden = Boolean(state.user);

    els.linkReportCsv.href = `/api/jobs/${job.job_id}/report.csv`;
    els.linkReportJson.href = `/api/jobs/${job.job_id}/report.json`;

    const elapsedStr = job.elapsed_seconds ? `Hoàn thành trong ${job.elapsed_seconds} giây` : "";
    const supportsSavePicker = typeof window.showSaveFilePicker === "function";
    const supportsDirPicker = typeof window.showDirectoryPicker === "function";

    if (outputs.length === 1) {
      els.singleCard.hidden = false;
      els.batchCard.hidden = true;

      const out = outputs[0];
      els.singleElapsed.textContent = elapsedStr;
      els.singleExtBadge.textContent = isDocx ? "DOCX" : "PDF";
      els.singleExtBadge.className = `ext-icon-badge ${isDocx ? "docx" : "pdf"}`;
      els.singleExtLocked.textContent = ext;

      const initialStem = stripExt(out.final_name, ext);
      els.singleNameStem.value = initialStem;

      els.singleMetaChips.innerHTML = "";
      const addChip = (txt, good = false) => {
        const s = document.createElement("span");
        s.className = good ? "meta-chip good" : "meta-chip";
        s.textContent = txt;
        els.singleMetaChips.appendChild(s);
      };
      addChip(formatBytes(out.byte_size || 0));
      addChip(`${out.page_count || 1} trang`);
      if (isDocx) {
        addChip(`✓ Giữ nguyên ${out.table_count || 0} bảng biểu`, true);
      } else if (out.searchable_text === true) {
        addChip("✓ Có lớp chữ OCR tìm kiếm được", true);
      } else if (out.searchable_text === null) {
        addChip("✓ Xuất chuẩn từ Office", true);
      }

      const syncSingleLinks = () => {
        const safeFull = `${cleanStemClient(els.singleNameStem.value)}${ext}`;
        const dlUrl = buildSingleDownloadUrl(job.job_id, out.output_id, safeFull);
        els.btnSingleDownload.href = dlUrl;
        els.btnSingleDownload.setAttribute("download", safeFull);
        out.final_name = safeFull;
      };
      syncSingleLinks();

      els.singleNameStem.oninput = () => {
        syncSingleLinks();
        schedulePatchOutputs(job.job_id, { [out.output_id]: out.final_name }, [out.output_id]);
      };

      els.btnSingleSaveAs.hidden = !supportsSavePicker;
      els.btnSingleSaveAs.onclick = () => {
        syncSingleLinks();
        saveSingleWithPicker(
          els.btnSingleDownload.href,
          out.final_name,
          isDocx,
          els.singleSaveFeedback,
          els.btnSingleDownload
        );
      };
    } else {
      els.singleCard.hidden = true;
      els.batchCard.hidden = false;
      els.batchElapsed.textContent = elapsedStr;

      const namesMap = {};
      const selectedSet = new Set();
      outputs.forEach((o) => {
        namesMap[o.output_id] = o.final_name;
        if (o.selected !== false) selectedSet.add(o.output_id);
      });

      const refreshBatchTopBar = () => {
        const chosen = outputs.filter((o) => selectedSet.has(o.output_id));
        const sumBytes = chosen.reduce((acc, o) => acc + (o.byte_size || 0), 0);
        els.batchTitle.textContent = `${chosen.length}/${outputs.length} tệp sẵn sàng tải xuống (${formatBytes(sumBytes)})`;

        const idsCsv = chosen.map((o) => o.output_id).join(",");
        const namesJson = JSON.stringify(namesMap);
        const zipParams = new URLSearchParams({ ids: idsCsv, names: namesJson });
        if (chosen.length > 0) {
          els.btnBatchZip.href = `/api/jobs/${job.job_id}/download-zip?${zipParams.toString()}`;
          els.btnBatchZip.setAttribute("download", isDocx ? "AutoSuite-Word.zip" : "AutoSuite-PDF.zip");
          els.btnBatchZip.removeAttribute("aria-disabled");
          els.btnBatchZip.tabIndex = 0;
        } else {
          els.btnBatchZip.removeAttribute("href");
          els.btnBatchZip.setAttribute("aria-disabled", "true");
          els.btnBatchZip.tabIndex = -1;
        }
        els.btnBatchZip.style.pointerEvents = chosen.length ? "auto" : "none";
        els.btnBatchZip.style.opacity = chosen.length ? "1" : "0.5";
        els.btnBatchFolder.disabled = chosen.length === 0;
      };

      els.batchList.innerHTML = "";
      outputs.forEach((out) => {
        const li = document.createElement("li");
        li.className = "batch-item";

        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.checked = selectedSet.has(out.output_id);
        chk.style.width = "18px";
        chk.style.height = "18px";

        const mainDiv = document.createElement("div");
        mainDiv.className = "batch-item-main";

        const group = document.createElement("div");
        group.className = "stem-input-group";
        const stemInput = document.createElement("input");
        stemInput.type = "text";
        stemInput.className = "name-stem-input";
        stemInput.style.fontSize = "0.9rem";
        stemInput.style.padding = "0.38rem 0.6rem";
        stemInput.value = stripExt(out.final_name, ext);
        const extSpan = document.createElement("span");
        extSpan.className = "ext-locked-pill";
        extSpan.textContent = ext;
        group.append(stemInput, extSpan);

        const metaDiv = document.createElement("div");
        metaDiv.className = "batch-item-meta";
        const detail = isDocx
          ? `Giữ ${out.table_count || 0} bảng`
          : out.searchable_text
            ? "Có OCR"
            : "PDF chuẩn";
        metaDiv.textContent = `Nguồn: ${out.source_label} · ${out.page_count || 1} trang · ${detail} · ${formatBytes(out.byte_size || 0)}`;
        mainDiv.append(group, metaDiv);

        const dlA = document.createElement("a");
        dlA.className = "btn btn-emerald btn-mini-dl";
        dlA.textContent = "⬇ Tải";
        const updateRowLink = () => {
          const full = `${cleanStemClient(stemInput.value)}${ext}`;
          namesMap[out.output_id] = full;
          out.final_name = full;
          dlA.href = buildSingleDownloadUrl(job.job_id, out.output_id, full);
          dlA.setAttribute("download", full);
        };
        updateRowLink();

        stemInput.addEventListener("input", () => {
          updateRowLink();
          refreshBatchTopBar();
          schedulePatchOutputs(job.job_id, namesMap, Array.from(selectedSet));
        });
        chk.addEventListener("change", () => {
          if (chk.checked) selectedSet.add(out.output_id);
          else selectedSet.delete(out.output_id);
          refreshBatchTopBar();
          schedulePatchOutputs(job.job_id, namesMap, Array.from(selectedSet));
        });

        li.append(chk, mainDiv, dlA);
        els.batchList.appendChild(li);
      });

      refreshBatchTopBar();
      els.btnBatchFolder.hidden = !supportsDirPicker;
      els.btnBatchFolder.onclick = () => {
        const items = outputs
          .filter((o) => selectedSet.has(o.output_id))
          .map((o) => ({ outputId: o.output_id, finalName: namesMap[o.output_id] }));
        if (items.length > 0) {
          saveBatchToFolder(job.job_id, items, els.batchSaveFeedback, els.btnBatchZip);
        }
      };
    }

    // Populate Preview Selector
    els.selectPreviewOutput.innerHTML = "";
    outputs.forEach((o) => {
      const opt = document.createElement("option");
      opt.value = o.output_id;
      opt.textContent = o.final_name;
      els.selectPreviewOutput.appendChild(opt);
    });
    els.previewSelectorRow.hidden = outputs.length <= 1;
    renderAiSuggestions(job);
  }

  async function loadPreviewForSelected() {
    const job = state.currentJob;
    if (!job || !job.outputs || !job.outputs.length) return;
    const outId = els.selectPreviewOutput.value || job.outputs[0].output_id;
    const cacheKey = `${job.job_id}:${outId}`;
    if (state.previewLoadedFor === cacheKey) return;
    state.previewLoadedFor = cacheKey;

    els.previewContainer.innerHTML = "";
    if (job.target_format !== "docx") {
      const iframe = document.createElement("iframe");
      iframe.className = "preview-iframe";
      iframe.loading = "lazy";
      iframe.src = `/api/jobs/${job.job_id}/outputs/${outId}/view`;
      els.previewContainer.appendChild(iframe);
      return;
    }

    const loading = document.createElement("div");
    loading.className = "muted-meta";
    loading.textContent = "Đang dựng bản xem trước bảng biểu Word…";
    els.previewContainer.appendChild(loading);

    try {
      const res = await fetch(`/api/jobs/${job.job_id}/outputs/${outId}/preview-blocks`);
      const data = await res.json();
      els.previewContainer.innerHTML = "";
      const blocks = data.blocks || [];
      if (!blocks.length) {
        const empty = document.createElement("div");
        empty.className = "muted-meta";
        empty.textContent = "Tệp Word (.docx) đã sẵn sàng tải xuống.";
        els.previewContainer.appendChild(empty);
        return;
      }
      let curPage = 0;
      for (const blk of blocks) {
        if (blk.page !== curPage) {
          curPage = blk.page;
          const pg = document.createElement("div");
          pg.className = "preview-page-sep";
          pg.textContent = `— Trang ${curPage} —`;
          els.previewContainer.appendChild(pg);
        }
        if (blk.type === "table" && Array.isArray(blk.rows)) {
          const tbl = document.createElement("table");
          tbl.className = "preview-table";
          for (const row of blk.rows) {
            const tr = document.createElement("tr");
            for (const cell of row) {
              const td = document.createElement("td");
              td.textContent = String(cell ?? "");
              tr.appendChild(td);
            }
            tbl.appendChild(tr);
          }
          els.previewContainer.appendChild(tbl);
        } else {
          const p = document.createElement(blk.heading ? "h4" : "p");
          p.style.margin = "0.35rem 0";
          p.textContent = String(blk.text || "");
          els.previewContainer.appendChild(p);
        }
      }
    } catch (_) {
      els.previewContainer.textContent = "Không tải được bản xem trước.";
    }
  }

  async function refreshAiModels() {
    els.aiOllamaModel.innerHTML = "<option value=''>Đang kiểm tra Ollama…</option>";
    try {
      const res = await fetch("/api/ai/models", { cache: "no-store" });
      const data = await res.json();
      state.aiModelsLoaded = true;
      if (data.default_openai_model) {
        els.aiOpenaiModel.value = data.default_openai_model;
      }
      els.aiOllamaModel.innerHTML = "";
      if (data.models && data.models.length > 0) {
        for (const m of data.models) {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          els.aiOllamaModel.appendChild(opt);
        }
      } else {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = data.ollama_running
          ? "Chưa cài model trong Ollama"
          : "Ollama chưa bật (127.0.0.1:11434)";
        els.aiOllamaModel.appendChild(opt);
      }
    } catch (_) {
      els.aiOllamaModel.innerHTML = "<option value=''>Không kết nối được Ollama</option>";
    }
  }

  function renderAiSuggestions(job) {
    els.aiResultsList.innerHTML = "";
    const withSug = (job.outputs || []).filter((o) => o.ai_suggestion || o.ai_error);
    els.btnApplyAiNames.hidden = !withSug.some((o) => o.ai_suggestion);
    for (const o of withSug) {
      const div = document.createElement("div");
      div.className = "ai-res-item";
      if (o.ai_suggestion) {
        const s = o.ai_suggestion;
        const badge =
          s.decision === "keep" ? "✓ Giữ" : s.decision === "skip" ? "⊘ Bỏ qua" : "👁 Xem lại";
        const strong = document.createElement("strong");
        strong.textContent = `${badge} · ${s.suggested_basename}.pdf`;
        const sub = document.createElement("div");
        sub.className = "muted-meta";
        sub.textContent = `${s.category} — ${s.reason}`;
        div.append(strong, sub);
      } else if (o.ai_error) {
        div.textContent = `⚠ ${o.final_name}: ${o.ai_error}`;
      }
      els.aiResultsList.appendChild(div);
    }
  }

  async function resetToUpload(deleteServerJob = true) {
    cleanupActiveTransport();
    const oldJob = state.currentJob;
    state.currentJob = null;
    state.files = [];
    inspectAndRenderStaging();
    navigateView("upload", true);
    if (deleteServerJob && oldJob && oldJob.job_id) {
      try {
        await fetch(`/api/jobs/${oldJob.job_id}`, { method: "DELETE" });
      } catch (_) {}
    }
  }

  // Event Wiring
  document.querySelectorAll(".tool-tab").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });

  document.querySelectorAll("[data-pdf-route]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.pdfRouteChoice = btn.dataset.pdfRoute;
      inspectAndRenderStaging();
    });
  });

  document.querySelectorAll("[data-img-merge]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.imgMergeChoice = btn.dataset.imgMerge === "true";
      inspectAndRenderStaging();
    });
  });

  // Persist autostart preference
  try {
    els.chkAutostart.checked = localStorage.getItem("autosuite_autostart") === "1";
    els.chkAutostart.addEventListener("change", () => {
      localStorage.setItem("autosuite_autostart", els.chkAutostart.checked ? "1" : "0");
    });
  } catch (_) {}

  els.btnPickFiles.addEventListener("click", (ev) => {
    ev.stopPropagation();
    els.fileInput.value = "";
    els.fileInput.click();
  });

  els.dropzone.addEventListener("click", () => {
    els.fileInput.value = "";
    els.fileInput.click();
  });

  els.dropzone.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      els.fileInput.value = "";
      els.fileInput.click();
    }
  });

  els.fileInput.addEventListener("change", () => {
    if (els.fileInput.files && els.fileInput.files.length) {
      addFiles(els.fileInput.files);
    }
  });

  els.btnAddMore.addEventListener("click", () => {
    els.fileInput.value = "";
    els.fileInput.click();
  });

  els.btnClearFiles.addEventListener("click", () => {
    state.files = [];
    inspectAndRenderStaging();
  });

  els.btnStartConvert.addEventListener("click", startConversion);

  els.btnCancelJob.addEventListener("click", () => resetToUpload(true));
  els.btnRetryEmpty.addEventListener("click", () => resetToUpload(true));
  els.btnConvertAnother.addEventListener("click", () => resetToUpload(true));
  els.brandHome.addEventListener("click", (ev) => {
    ev.preventDefault();
    resetToUpload(false);
  });

  // Global Drag & Drop + Clipboard Ctrl+V Screenshot Paste
  let dragDepth = 0;
  window.addEventListener("dragenter", (ev) => {
    if (ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files")) {
      ev.preventDefault();
      dragDepth++;
      els.dragOverlay.hidden = false;
      els.dropzone.classList.add("dragover");
    }
  });

  window.addEventListener("dragover", (ev) => {
    if (ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files")) {
      ev.preventDefault();
    }
  });

  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      els.dragOverlay.hidden = true;
      els.dropzone.classList.remove("dragover");
    }
  });

  window.addEventListener("drop", (ev) => {
    dragDepth = 0;
    els.dragOverlay.hidden = true;
    els.dropzone.classList.remove("dragover");
    if (ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files.length) {
      ev.preventDefault();
      addFiles(ev.dataTransfer.files);
    }
  });

  window.addEventListener("paste", (ev) => {
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    const files = ev.clipboardData && ev.clipboardData.files;
    if (files && files.length > 0) {
      ev.preventDefault();
      addFiles(files);
      showToast(`Đã dán ${files.length} tệp từ bộ nhớ tạm.`);
    }
  });

  // Lazy Drawers
  els.drawerPreview.addEventListener("toggle", () => {
    if (els.drawerPreview.open) loadPreviewForSelected();
  });

  els.selectPreviewOutput.addEventListener("change", () => {
    state.previewLoadedFor = "";
    if (els.drawerPreview.open) loadPreviewForSelected();
  });

  els.drawerAi.addEventListener("toggle", () => {
    if (els.drawerAi.open && !state.aiModelsLoaded) {
      refreshAiModels();
    }
  });

  els.aiProvider.addEventListener("change", () => {
    const isCloud = els.aiProvider.value === "openai";
    els.aiOllamaWrap.hidden = isCloud;
    els.aiOpenaiWrap.hidden = !isCloud;
    els.aiConsentWrap.hidden = !isCloud;
  });

  els.btnRefreshOllama.addEventListener("click", refreshAiModels);

  els.btnRunAi.addEventListener("click", async () => {
    const job = state.currentJob;
    if (!job) return;
    const provider = els.aiProvider.value;
    const model = provider === "ollama" ? els.aiOllamaModel.value : els.aiOpenaiModel.value.trim();
    const filterRequest = els.aiPrompt.value.trim();
    if (!model) {
      showToast("Hãy chọn hoặc nhập tên model AI trước khi chạy.", true);
      return;
    }
    els.btnRunAi.disabled = true;
    els.btnRunAi.textContent = "⏳ Đang phân loại bằng AI…";
    try {
      const res = await fetch(`/api/jobs/${job.job_id}/ai-classify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          filter_request: filterRequest,
          cloud_consent: els.aiConsent.checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Phân loại AI thất bại.", true);
      } else {
        renderDownloadScreen(data);
        els.drawerAi.open = true;
      }
    } catch (_) {
      showToast("Lỗi kết nối khi gọi AI.", true);
    } finally {
      els.btnRunAi.disabled = false;
      els.btnRunAi.textContent = "✨ Chạy AI gợi ý tên tệp";
    }
  });

  els.btnApplyAiNames.addEventListener("click", async () => {
    const job = state.currentJob;
    if (!job) return;
    const names = {};
    const selected = [];
    for (const o of job.outputs || []) {
      if (o.ai_suggestion) {
        names[o.output_id] = `${o.ai_suggestion.suggested_basename}.pdf`;
        if (o.ai_suggestion.decision !== "skip") selected.push(o.output_id);
      } else {
        names[o.output_id] = o.final_name;
        selected.push(o.output_id);
      }
    }
    try {
      const res = await fetch(`/api/jobs/${job.job_id}/outputs`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ names, selected_ids: selected }),
      });
      if (res.ok) {
        const updated = await res.json();
        renderDownloadScreen(updated);
        showToast("Đã áp dụng tên gợi ý từ AI.");
      }
    } catch (_) {}
  });

  // -------------------------------------------------------------------------
  // Authentication, Account History & Admin RBAC Logic
  // -------------------------------------------------------------------------

  function clearAuthErrors() {
    els.authErrorBox.hidden = true;
    els.authErrorBox.textContent = "";
    [
      els.errLoginIdentifier,
      els.errLoginPassword,
      els.errSignupUsername,
      els.errSignupEmail,
      els.errSignupPassword,
      els.errSignupConfirm,
    ].forEach((el) => {
      if (el) el.textContent = "";
    });
  }

  function switchAuthTab(tabName) {
    clearAuthErrors();
    const isSignup = tabName === "signup";
    els.tabAuthLogin.classList.toggle("active", !isSignup);
    els.tabAuthSignup.classList.toggle("active", isSignup);
    els.formLogin.hidden = isSignup;
    els.formSignup.hidden = !isSignup;
  }

  function formatDateVi(isoStr) {
    if (!isoStr) return "";
    try {
      const d = new Date(isoStr);
      return d.toLocaleString("vi-VN", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return isoStr;
    }
  }

  function renderAuthHeader() {
    const u = state.user;
    els.authGuestControls.hidden = Boolean(u);
    els.authUserControls.hidden = !u;
    if (els.guestHistoryNudge && !els.viewDownload.hidden && state.currentJob && (state.currentJob.outputs || []).length > 0) {
      els.guestHistoryNudge.hidden = Boolean(u);
    }
    if (!u) return;

    const initial = (u.username || u.email || "U").trim().charAt(0).toUpperCase();
    els.navUserAvatar.textContent = initial;
    els.navUserName.textContent = u.username;
    els.navUserRole.textContent = u.role;
    els.navUserRole.className = u.role === "Admin" ? "role-badge admin" : "role-badge";
    els.navBtnAdmin.hidden = u.role !== "Admin";
  }

  async function refreshCurrentUser() {
    try {
      const res = await fetch("/api/auth/me", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        state.user = data.authenticated ? data.user : null;
      } else {
        state.user = null;
      }
    } catch (_) {
      state.user = null;
    }
    state.authChecked = true;
    renderAuthHeader();
    return state.user;
  }

  async function loadAccountScreen() {
    if (!state.authChecked) await refreshCurrentUser();
    if (!state.user) {
      navigateView("login", true);
      showToast("Vui lòng đăng nhập để xem hồ sơ và lịch sử chuyển đổi.", true);
      return;
    }
    const u = state.user;
    els.accountAvatarLg.textContent = (u.username || "U").trim().charAt(0).toUpperCase();
    els.accountUsername.textContent = u.username;
    els.accountRoleBadge.textContent = u.role;
    els.accountRoleBadge.className = u.role === "Admin" ? "role-badge admin" : "role-badge";
    els.accountEmail.textContent = u.email;
    els.accountCreated.textContent = `Tham gia lúc: ${formatDateVi(u.created_at)}`;
    els.pwChangeMsg.hidden = true;
    navigateView("account", false);

    try {
      const res = await fetch("/api/account/history", { cache: "no-store" });
      if (res.status === 401) {
        state.user = null;
        renderAuthHeader();
        navigateView("login", true);
        return;
      }
      const data = await res.json();
      const items = data.items || [];
      els.historyList.innerHTML = "";
      els.historyEmpty.hidden = items.length > 0;
      for (const item of items) {
        const li = document.createElement("li");
        li.className = "history-item";

        const left = document.createElement("div");
        left.className = "history-left";
        const badge = document.createElement("span");
        badge.className = `history-fmt ${item.target_format === "docx" ? "docx" : "pdf"}`;
        badge.textContent = item.target_format === "docx" ? "DOCX" : "PDF";

        const info = document.createElement("div");
        info.style.minWidth = "0";
        const nameDiv = document.createElement("div");
        nameDiv.className = "history-names";
        nameDiv.textContent = item.summary_names;
        const subDiv = document.createElement("div");
        subDiv.className = "history-sub";
        subDiv.textContent = `${item.file_count} tệp · ${formatBytes(item.total_bytes || 0)} · ${formatDateVi(item.created_at)}`;
        info.append(nameDiv, subDiv);
        left.append(badge, info);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn-mini";
        delBtn.textContent = "Xóa";
        delBtn.addEventListener("click", async () => {
          await fetch(`/api/account/history/${item.id}`, { method: "DELETE" });
          li.remove();
          if (!els.historyList.children.length) els.historyEmpty.hidden = false;
        });

        li.append(left, delBtn);
        els.historyList.appendChild(li);
      }
    } catch (_) {}
  }

  async function loadAdminScreen() {
    if (!state.authChecked) await refreshCurrentUser();
    if (!state.user) {
      navigateView("login", true);
      showToast("Vui lòng đăng nhập tài khoản Quản trị (Admin).", true);
      return;
    }
    navigateView("admin", false);

    try {
      const res = await fetch("/api/admin/users", { cache: "no-store" });
      if (res.status === 401) {
        state.user = null;
        renderAuthHeader();
        navigateView("login", true);
        return;
      }
      if (res.status === 403) {
        els.adminForbiddenCard.hidden = false;
        els.adminPanelCard.hidden = true;
        return;
      }
      const data = await res.json();
      els.adminForbiddenCard.hidden = true;
      els.adminPanelCard.hidden = false;
      els.adminUsersTbody.innerHTML = "";

      for (const u of data.users || []) {
        const tr = document.createElement("tr");
        const cells = [
          String(u.id),
          u.username + (state.user && u.id === state.user.id ? " (Bạn)" : ""),
          u.email,
        ];
        cells.forEach((txt) => {
          const td = document.createElement("td");
          td.textContent = txt;
          tr.appendChild(td);
        });

        const tdRole = document.createElement("td");
        const rb = document.createElement("span");
        rb.className = u.role === "Admin" ? "role-badge admin" : "role-badge";
        rb.textContent = u.role;
        tdRole.appendChild(rb);
        tr.appendChild(tdRole);

        const tdDate = document.createElement("td");
        tdDate.textContent = formatDateVi(u.created_at);
        tr.appendChild(tdDate);

        const tdAct = document.createElement("td");
        tdAct.style.display = "flex";
        tdAct.style.gap = "0.4rem";

        const nextRole = u.role === "Admin" ? "User" : "Admin";
        const roleBtn = document.createElement("button");
        roleBtn.type = "button";
        roleBtn.className = "btn-mini";
        roleBtn.textContent = nextRole === "Admin" ? "Nâng Admin" : "Hạ User";
        roleBtn.addEventListener("click", async () => {
          const r = await fetch(`/api/admin/users/${u.id}/role`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role: nextRole }),
          });
          const resp = await r.json();
          if (!r.ok) showToast(resp.error || "Không đổi được quyền.", true);
          else {
            showToast(`Đã đổi quyền ${u.username} sang ${nextRole}.`);
            await refreshCurrentUser();
            loadAdminScreen();
          }
        });
        tdAct.appendChild(roleBtn);

        if (!state.user || u.id !== state.user.id) {
          const rmBtn = document.createElement("button");
          rmBtn.type = "button";
          rmBtn.className = "btn-mini";
          rmBtn.style.color = "var(--rose)";
          rmBtn.textContent = "Xóa";
          rmBtn.addEventListener("click", async () => {
            const r = await fetch(`/api/admin/users/${u.id}`, { method: "DELETE" });
            const resp = await r.json();
            if (!r.ok) showToast(resp.error || "Không xóa được người dùng.", true);
            else {
              showToast(`Đã xóa tài khoản ${u.username}.`);
              loadAdminScreen();
            }
          });
          tdAct.appendChild(rmBtn);
        }

        tr.appendChild(tdAct);
        els.adminUsersTbody.appendChild(tr);
      }
    } catch (_) {
      showToast("Không tải được danh sách người dùng.", true);
    }
  }

  async function performLogout() {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (_) {}
    state.user = null;
    renderAuthHeader();
    showToast("Đã đăng xuất an toàn.");
    navigateView("upload", true);
  }

  els.tabAuthLogin.addEventListener("click", () => navigateView("login", true));
  els.tabAuthSignup.addEventListener("click", () => navigateView("signup", true));
  els.navBtnLogout.addEventListener("click", performLogout);
  els.btnAccountLogout.addEventListener("click", performLogout);
  els.btnRefreshHistory.addEventListener("click", loadAccountScreen);
  els.btnRefreshAdmin.addEventListener("click", loadAdminScreen);

  document.querySelectorAll(".btn-pw-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = $(btn.dataset.pwTarget);
      if (!target) return;
      target.type = target.type === "password" ? "text" : "password";
    });
  });

  els.formLogin.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearAuthErrors();
    els.btnSubmitLogin.disabled = true;
    els.btnSubmitLogin.textContent = "⏳ Đang đăng nhập…";
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: els.loginIdentifier.value.trim(),
          password: els.loginPassword.value,
          remember_me: els.loginRemember.checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        els.authErrorBox.textContent = data.error || "Đăng nhập thất bại.";
        els.authErrorBox.hidden = false;
        if (data.field_errors) {
          if (data.field_errors.identifier) els.errLoginIdentifier.textContent = data.field_errors.identifier;
          if (data.field_errors.password) els.errLoginPassword.textContent = data.field_errors.password;
        }
      } else {
        state.user = data.user;
        renderAuthHeader();
        els.formLogin.reset();
        showToast(`Chào mừng ${data.user.username}!`);
        navigateView("upload", true);
      }
    } catch (_) {
      els.authErrorBox.textContent = "Không kết nối được máy chủ.";
      els.authErrorBox.hidden = false;
    } finally {
      els.btnSubmitLogin.disabled = false;
      els.btnSubmitLogin.textContent = "🔐 Đăng nhập";
    }
  });

  els.formSignup.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearAuthErrors();
    els.btnSubmitSignup.disabled = true;
    els.btnSubmitSignup.textContent = "⏳ Đang tạo tài khoản…";
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: els.signupUsername.value.trim(),
          email: els.signupEmail.value.trim(),
          password: els.signupPassword.value,
          confirm_password: els.signupConfirm.value,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        els.authErrorBox.textContent = data.error || "Đăng ký thất bại.";
        els.authErrorBox.hidden = false;
        if (data.field_errors) {
          if (data.field_errors.username) els.errSignupUsername.textContent = data.field_errors.username;
          if (data.field_errors.email) els.errSignupEmail.textContent = data.field_errors.email;
          if (data.field_errors.password) els.errSignupPassword.textContent = data.field_errors.password;
          if (data.field_errors.confirm_password) els.errSignupConfirm.textContent = data.field_errors.confirm_password;
        }
      } else {
        state.user = data.user;
        renderAuthHeader();
        els.formSignup.reset();
        showToast(`Đăng ký thành công! Vai trò: ${data.user.role}.`);
        navigateView("upload", true);
      }
    } catch (_) {
      els.authErrorBox.textContent = "Không kết nối được máy chủ.";
      els.authErrorBox.hidden = false;
    } finally {
      els.btnSubmitSignup.disabled = false;
      els.btnSubmitSignup.textContent = "✨ Đăng ký & Vào sử dụng ngay";
    }
  });

  els.formChangePw.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    els.pwChangeMsg.hidden = true;
    els.btnSavePw.disabled = true;
    try {
      const res = await fetch("/api/account/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: els.pwCurrent.value,
          new_password: els.pwNew.value,
          confirm_password: els.pwConfirm.value,
        }),
      });
      const data = await res.json();
      els.pwChangeMsg.hidden = false;
      if (!res.ok) {
        els.pwChangeMsg.className = "alert alert-error";
        els.pwChangeMsg.textContent = data.error || "Đổi mật khẩu thất bại.";
      } else {
        els.pwChangeMsg.className = "alert alert-success";
        els.pwChangeMsg.textContent = data.message || "Đã cập nhật mật khẩu.";
        els.formChangePw.reset();
      }
    } catch (_) {
      els.pwChangeMsg.hidden = false;
      els.pwChangeMsg.className = "alert alert-error";
      els.pwChangeMsg.textContent = "Lỗi kết nối máy chủ.";
    } finally {
      els.btnSavePw.disabled = false;
    }
  });

  // Browser History Back / Forward Support
  async function syncFromLocationHash() {
    const h = location.hash || "";
    if (h === "#login") {
      navigateView("login", false);
    } else if (h === "#signup") {
      navigateView("signup", false);
    } else if (h === "#account") {
      await loadAccountScreen();
    } else if (h === "#admin") {
      await loadAdminScreen();
    } else if (h.startsWith("#download/")) {
      const jobId = h.slice("#download/".length).trim();
      if (state.currentJob && state.currentJob.job_id === jobId) {
        renderDownloadScreen(state.currentJob);
        navigateView("download", false, jobId);
        return;
      }
      const ok = await fetchJobSnapshot(jobId, (snap) => {
        renderDownloadScreen(snap);
        navigateView("download", false, jobId);
      });
      if (!ok) navigateView("upload", false);
    } else if (h === "#converting" && (state.activeXhr || state.activeSse || state.pollTimer)) {
      navigateView("converting", false);
    } else {
      cleanupActiveTransport();
      inspectAndRenderStaging();
      navigateView("upload", false);
    }
  }

  window.addEventListener("hashchange", syncFromLocationHash);
  refreshCurrentUser().then(() => syncFromLocationHash());
})();
