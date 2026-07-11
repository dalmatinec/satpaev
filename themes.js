// ==========================================================================
// Управление темами
// Подключается отдельно, не влияет на основной JS
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  
  const THEMES = ['dark', 'sunset', 'sunrise', 'light'];
  const STORAGE_KEY = 'murlychestvo-theme';
  const DEFAULT_THEME = 'dark';
  
  let currentTheme = localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
  let dropdownOpen = false;
  
  // ---------- Элементы ----------
  const header = document.querySelector('.header-inner');
  const navList = document.getElementById('nav-list');
  
  // ---------- Создаём переключатель ----------
  const createThemeToggle = () => {
    // Контейнер
    const wrapper = document.createElement('div');
    wrapper.className = 'theme-toggle-wrapper';
    
    // Кнопка-иконка
    const btn = document.createElement('button');
    btn.className = 'theme-toggle-btn';
    btn.setAttribute('aria-label', 'Переключить тему');
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="5"/>
        <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
      </svg>
    `;
    
    // Выпадающее меню
    const dropdown = document.createElement('div');
    dropdown.className = 'theme-dropdown';
    
    // Наполняем меню
    THEMES.forEach(theme => {
      const item = document.createElement('button');
      item.className = 'theme-dropdown-item';
      item.dataset.theme = theme;
      if (theme === currentTheme) item.classList.add('is-active');
      
      // Миниатюры цветов
      const swatches = document.createElement('span');
      swatches.className = 'swatches';
      
      const colors = {
        dark: ['#101214', '#1D7AFC', '#DEE4EA'],
        sunset: ['#151c19', '#C0AB92', '#ecd2c5'],
        sunrise: ['#ecd2c5', '#a04d66', '#4f2733'],
        light: ['#F7F8F9', '#1D7AFC', '#091E42']
      };
      
      colors[theme].forEach(color => {
        const swatch = document.createElement('span');
        swatch.className = 'swatch';
        swatch.style.background = color;
        swatches.appendChild(swatch);
      });
      
      const label = document.createElement('span');
      label.className = 'label';
      label.textContent = theme.charAt(0).toUpperCase() + theme.slice(1);
      
      const check = document.createElement('span');
      check.className = 'check';
      check.textContent = '✓';
      
      item.appendChild(swatches);
      item.appendChild(label);
      item.appendChild(check);
      
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        applyTheme(theme);
        closeDropdown();
      });
      
      dropdown.appendChild(item);
    });
    
    wrapper.appendChild(btn);
    wrapper.appendChild(dropdown);
    
    // Вставляем в шапку
    const nav = document.querySelector('.main-nav');
    if (nav) {
      nav.appendChild(wrapper);
    } else {
      // Если .main-nav нет, вставляем в .header-inner
      const headerInner = document.querySelector('.header-inner');
      if (headerInner) {
        const navToggle = document.getElementById('nav-toggle');
        if (navToggle) {
          headerInner.insertBefore(wrapper, navToggle.nextSibling);
        } else {
          headerInner.appendChild(wrapper);
        }
      }
    }
    
    // ---------- События ----------
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleDropdown();
    });
    
    // Закрытие при клике вне
    document.addEventListener('click', (e) => {
      if (!wrapper.contains(e.target)) {
        closeDropdown();
      }
    });
    
    // Закрытие при Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dropdownOpen) {
        closeDropdown();
      }
    });
    
    return { wrapper, btn, dropdown };
  };
  
  // ---------- Функции ----------
  const toggleDropdown = () => {
    dropdownOpen = !dropdownOpen;
    const dropdown = document.querySelector('.theme-dropdown');
    const btn = document.querySelector('.theme-toggle-btn');
    if (dropdown) {
      dropdown.classList.toggle('is-open', dropdownOpen);
    }
    if (btn) {
      btn.setAttribute('aria-expanded', dropdownOpen ? 'true' : 'false');
    }
  };
  
  const closeDropdown = () => {
    dropdownOpen = false;
    const dropdown = document.querySelector('.theme-dropdown');
    const btn = document.querySelector('.theme-toggle-btn');
    if (dropdown) {
      dropdown.classList.remove('is-open');
    }
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
    }
  };
  
  const applyTheme = (theme) => {
    if (!THEMES.includes(theme)) return;
    
    currentTheme = theme;
    
    // Устанавливаем data-theme
    document.documentElement.setAttribute('data-theme', theme);
    
    // Сохраняем
    localStorage.setItem(STORAGE_KEY, theme);
    
    // Обновляем активный пункт в меню
    document.querySelectorAll('.theme-dropdown-item').forEach(item => {
      const isActive = item.dataset.theme === theme;
      item.classList.toggle('is-active', isActive);
    });
  };
  
  // ---------- Инициализация ----------
  const init = () => {
    // Создаём переключатель
    createThemeToggle();
    
    // Применяем сохранённую тему
    applyTheme(currentTheme);
  };
  
  // ---------- Запуск ----------
  init();
  
});