Home replica
===========

This folder contains the home page replica template and static assets used for a quick local preview.

Files added/modified
- templates/products/home_replica.html - Tailwind based replica template (uses placeholders)
- static/products/home_replica.js - Carousel logic with accessibility and controls
- static/products/placeholder.svg - Placeholder image used when product.image is absent

Preview
1. Start Django dev server:

```powershell
python manage.py runserver
```

2. Open:

http://localhost:8000/products/home/

Notes
- Tailwind is provided via CDN in the template for now. For production, consider installing Tailwind and building a CSS file.
- Replace `static/products/placeholder.svg` with your images for better visual fidelity.
- Product CTAs post to the claim endpoint (`/products/claim/`) which runs `complete_product_task` for the selected product.

Tailwind production build
------------------------
If you want a production-ready Tailwind CSS file (recommended), run these commands in the project root:

```powershell
npm install
npm run build:css
```

This will generate `products/static/products/home_replica.css` which you can include instead of the CDN link in the template.

Accessibility
- Carousel has keyboard controls (left/right arrows), aria labels, and dot controls.

If you want me to set up a production Tailwind build or further tweak styling to match the target pixel-by-pixel, say "go 6" or "go 7".