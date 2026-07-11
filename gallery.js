// ==========================================================================
// Галерея "Наши котики"
// Подключается отдельно, не влияет на основной JS
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {

  // ---------- Конфигурация ----------
  const PHOTOS = [
    'cat1.jpg',
    'cat2.jpg',
    'cat3.jpg',
    'cat4.jpg',
    'cat5.jpg',
    'cat6.jpg'
  ];

  const IMAGE_PATH = 'images/';

  // ---------- Состояние ----------
  let currentImageIndex = 0;
  let isModalOpen = false;
  let isViewerOpen = false;

  // ---------- Создание карточки-папки ----------
  const createFolder = () => {
    const section = document.getElementById('cats');
    if (!section) return;

    const inner = section.querySelector('.section-inner');
    if (!inner) return;

    // Убираем старую кнопку если есть
    const oldBtn = inner.querySelector('#cats-gallery-btn');
    if (oldBtn) oldBtn.remove();

    // Контейнер
    const folder = document.createElement('div');
    folder.className = 'gallery-folder';
    folder.setAttribute('role', 'button');
    folder.setAttribute('tabindex', '0');
    folder.setAttribute('aria-label', 'Открыть галерею котиков');

    folder.innerHTML = `
      <div class="gallery-folder-inner">
        <span class="badge">${PHOTOS.length} фото</span>
        <div class="gallery-folder-preview">
          ${PHOTOS.slice(0, 6).map((photo, i) => `
            <img src="${IMAGE_PATH}${photo}" alt="Котик ${i + 1}" loading="lazy">
          `).join('')}
        </div>
        <div class="gallery-folder-label">
          <span>📁 Наши котики</span>
          <span class="arrow">→</span>
        </div>
      </div>
    `;

    folder.addEventListener('click', openModal);
    folder.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openModal();
      }
    });

    inner.appendChild(folder);
  };

  // ---------- Создание модального окна ----------
  const createModal = () => {
    // Overlay
    const overlay = document.createElement('div');
    overlay.className = 'gallery-modal-overlay';
    overlay.id = 'gallery-modal';

    overlay.innerHTML = `
      <div class="gallery-modal">
        <div class="gallery-modal-header">
          <h3>🐱 Наши котики</h3>
          <button class="gallery-modal-close" aria-label="Закрыть галерею">✕</button>
        </div>
        <div class="gallery-modal-grid" id="gallery-grid">
          ${PHOTOS.map((photo, i) => `
            <div class="gallery-thumb" data-index="${i}">
              <img src="${IMAGE_PATH}${photo}" alt="Котик ${i + 1}" loading="lazy">
            </div>
          `).join('')}
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // ---------- События модалки ----------
    const closeBtn = overlay.querySelector('.gallery-modal-close');
    const grid = overlay.querySelector('#gallery-grid');

    // Закрытие по кнопке
    closeBtn.addEventListener('click', closeModal);

    // Закрытие по overlay
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    // Клик по фото → открыть просмотр
    grid.addEventListener('click', (e) => {
      const thumb = e.target.closest('.gallery-thumb');
      if (!thumb) return;
      const index = parseInt(thumb.dataset.index, 10);
      if (!isNaN(index)) openViewer(index);
    });

    // ESC
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (isViewerOpen) {
          closeViewer();
        } else if (isModalOpen) {
          closeModal();
        }
      }
    });

    return overlay;
  };

  // ---------- Создание просмотрщика ----------
  const createViewer = () => {
    const viewer = document.createElement('div');
    viewer.className = 'gallery-viewer';
    viewer.id = 'gallery-viewer';

    viewer.innerHTML = `
      <button class="gallery-viewer-close" aria-label="Закрыть фото">✕</button>
      <img src="" alt="Просмотр фото" id="viewer-image">
      <div class="gallery-viewer-counter" id="viewer-counter"></div>
    `;

    document.body.appendChild(viewer);

    // Закрытие
    const closeBtn = viewer.querySelector('.gallery-viewer-close');
    closeBtn.addEventListener('click', closeViewer);

    viewer.addEventListener('click', (e) => {
      if (e.target === viewer) closeViewer();
    });

    // Стрелки
    document.addEventListener('keydown', (e) => {
      if (!isViewerOpen) return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateViewer(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigateViewer(1);
      }
    });

    return viewer;
  };

  // ---------- Функции модалки ----------
  const openModal = () => {
    const modal = document.getElementById('gallery-modal');
    if (!modal) return;
    isModalOpen = true;
    modal.classList.add('is-open');
    document.body.style.overflow = 'hidden';
  };

  const closeModal = () => {
    const modal = document.getElementById('gallery-modal');
    if (!modal) return;
    if (isViewerOpen) closeViewer();
    isModalOpen = false;
    modal.classList.remove('is-open');
    document.body.style.overflow = '';
  };

  // ---------- Функции просмотрщика ----------
  const openViewer = (index) => {
    const viewer = document.getElementById('gallery-viewer');
    const img = document.getElementById('viewer-image');
    const counter = document.getElementById('viewer-counter');
    if (!viewer || !img || !counter) return;

    currentImageIndex = index;
    img.src = IMAGE_PATH + PHOTOS[index];
    img.alt = `Котик ${index + 1}`;
    counter.textContent = `${index + 1} / ${PHOTOS.length}`;

    isViewerOpen = true;
    viewer.classList.add('is-open');
  };

  const closeViewer = () => {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer) return;
    isViewerOpen = false;
    viewer.classList.remove('is-open');
  };

  const navigateViewer = (direction) => {
    let newIndex = currentImageIndex + direction;
    if (newIndex < 0) newIndex = PHOTOS.length - 1;
    if (newIndex >= PHOTOS.length) newIndex = 0;
    openViewer(newIndex);
  };

  // ---------- Инициализация ----------
  const init = () => {
    // Ждём пока отрендерится секция
    const checkSection = () => {
      const section = document.getElementById('cats');
      if (section) {
        createFolder();
        createModal();
        createViewer();
      } else {
        setTimeout(checkSection, 100);
      }
    };
    checkSection();
  };

  init();

});