document.addEventListener('DOMContentLoaded', () => {

  /* ---------- Год в футере ---------- */
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ---------- Шапка: стиль при прокрутке ---------- */
  const header = document.getElementById('site-header');
  const onScrollHeader = () => {
    if (window.scrollY > 12) {
      header.classList.add('scrolled');
    } else {
      header.classList.remove('scrolled');
    }
  };
  onScrollHeader();
  window.addEventListener('scroll', onScrollHeader, { passive: true });

  /* ---------- Мобильное меню ---------- */
  const navToggle = document.getElementById('nav-toggle');
  const navList = document.getElementById('nav-list');

  if (navToggle && navList) {
    navToggle.addEventListener('click', () => {
      const isOpen = navList.classList.toggle('is-open');
      navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    navList.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        navList.classList.remove('is-open');
        navToggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* ---------- Плавная прокрутка по якорям ---------- */
  document.querySelectorAll('[data-scroll]').forEach((link) => {
    link.addEventListener('click', (e) => {
      const targetId = link.getAttribute('href');
      if (!targetId || targetId.charAt(0) !== '#') return;
      const target = document.querySelector(targetId);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  /* ---------- Появление блоков при прокрутке ---------- */
  const revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

    revealEls.forEach((el) => observer.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }

  /* ---------- Кнопка "Наверх" ---------- */
  const scrollTopBtn = document.getElementById('scroll-top');
  if (scrollTopBtn) {
    const toggleScrollTop = () => {
      scrollTopBtn.classList.toggle('is-visible', window.scrollY > 480);
    };
    toggleScrollTop();
    window.addEventListener('scroll', toggleScrollTop, { passive: true });

    scrollTopBtn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ---------- Раздел "Наши котики": кнопка пока неактивна ---------- */
  const catsBtn = document.getElementById('cats-gallery-btn');
  if (catsBtn) {
    catsBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Галерея котиков появится здесь позже — кнопка намеренно ничего не делает.
    });
  }

  /* ---------- Аккуратный запасной вид, пока PNG-иконки ещё не добавлены ---------- */
  document.querySelectorAll('.link-row-icon img').forEach((img) => {
    img.addEventListener('error', () => {
      img.classList.add('icon-missing');
      img.parentElement.classList.add('icon-placeholder');
    }, { once: true });
  });

});
