export default [
  {
    files: ['**/*.ts', '**/*.js'],
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
    },
  },
  {
    ignores: ['coverage/**', 'node_modules/**', '.governance/**', 'dist/**'],
  },
];
