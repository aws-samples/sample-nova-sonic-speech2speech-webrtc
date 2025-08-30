#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const chalk = require('react-dev-utils/chalk');
const { execSync } = require('child_process');

console.log(chalk.blue('🚀 Starting production deployment process...'));

// Check environment
console.log(chalk.cyan('1. Checking environment configuration...'));
try {
  execSync('npm run check-env', { stdio: 'inherit' });
} catch (error) {
  console.log(chalk.red('❌ Environment check failed'));
  process.exit(1);
}

// Clean previous build
console.log(chalk.cyan('2. Cleaning previous build...'));
const buildPath = path.join(__dirname, '..', 'build');
if (fs.existsSync(buildPath)) {
  fs.rmSync(buildPath, { recursive: true, force: true });
  console.log(chalk.green('✅ Previous build cleaned'));
}

// Build for production
console.log(chalk.cyan('3. Building for production...'));
try {
  execSync('npm run build', { stdio: 'inherit' });
  console.log(chalk.green('✅ Production build completed'));
} catch (error) {
  console.log(chalk.red('❌ Build failed'));
  process.exit(1);
}

// Verify build
console.log(chalk.cyan('4. Verifying build output...'));
const indexPath = path.join(buildPath, 'index.html');
if (fs.existsSync(indexPath)) {
  const stats = fs.statSync(buildPath);
  console.log(chalk.green('✅ Build verification passed'));
  console.log(chalk.gray(`   Build directory: ${buildPath}`));
  console.log(chalk.gray(`   Build size: ${(stats.size / 1024).toFixed(2)} KB`));
} else {
  console.log(chalk.red('❌ Build verification failed - index.html not found'));
  process.exit(1);
}

console.log(chalk.green('🎉 Deployment preparation completed!'));
console.log(chalk.cyan('Next steps:'));
console.log(chalk.gray('  - Test locally: npm run serve'));
console.log(chalk.gray('  - Deploy the build/ directory to your web server'));
console.log(chalk.gray('  - Ensure your server serves index.html for all routes (SPA routing)'));