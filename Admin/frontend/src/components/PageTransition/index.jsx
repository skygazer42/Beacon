import React from 'react';
import PropTypes from 'prop-types';

/**
 * Wraps page content with a CSS-only slide-up entrance animation.
 * Relies on the `beacon-slide-up` keyframe defined in motion.css
 * and the `.beacon-page-enter` class in AppLayout.css.
 *
 * Respects `prefers-reduced-motion` via the CSS media query —
 * the animation is disabled automatically when the user prefers reduced motion.
 */
export default function PageTransition({ children }) {
  return (
    <div className="beacon-page-enter">
      {children}
    </div>
  );
}

PageTransition.propTypes = {
  children: PropTypes.node,
};
