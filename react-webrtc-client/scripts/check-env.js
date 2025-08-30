#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const chalk = require('react-dev-utils/chalk');

// Check if .env file exists
const envPath = path.join(__dirname, '..', '.env');
const envTemplatePath = path.join(__dirname, '..', '.env.template');

console.log(chalk.blue('🔍 Checking environment configuration...'));

if (!fs.existsSync(envPath)) {
  console.log(chalk.yellow('⚠️  .env file not found'));
  
  if (fs.existsSync(envTemplatePath)) {
    console.log(chalk.cyan('📋 .env.template found. Please copy it to .env and configure:'));
    console.log(chalk.gray('   cp .env.template .env'));
    console.log(chalk.gray('   # Then edit .env with your AWS credentials'));
  } else {
    console.log(chalk.red('❌ .env.template not found'));
    process.exit(1);
  }
} else {
  console.log(chalk.green('✅ .env file found'));
  
  // Check for required environment variables
  require('dotenv').config({ path: envPath });
  
  const requiredVars = [
    'REACT_APP_AWS_REGION',
    'REACT_APP_AWS_ACCESS_KEY_ID',
    'REACT_APP_AWS_SECRET_ACCESS_KEY',
    'REACT_APP_KVS_CHANNEL_NAME'
  ];
  
  const missingVars = requiredVars.filter(varName => {
    const value = process.env[varName];
    return !value || value.includes('your_') || value.includes('_here');
  });
  
  if (missingVars.length > 0) {
    console.log(chalk.yellow('⚠️  Missing or placeholder values for:'));
    missingVars.forEach(varName => {
      console.log(chalk.gray(`   - ${varName}`));
    });
    console.log(chalk.cyan('Please update your .env file with actual values'));
  } else {
    console.log(chalk.green('✅ All required environment variables are configured'));
  }
}

// Check Node.js version
const nodeVersion = process.version;
const majorVersion = parseInt(nodeVersion.slice(1).split('.')[0]);

if (majorVersion < 16) {
  console.log(chalk.red(`❌ Node.js ${nodeVersion} is not supported. Please use Node.js 16 or higher.`));
  process.exit(1);
} else {
  console.log(chalk.green(`✅ Node.js ${nodeVersion} is supported`));
}

console.log(chalk.green('🎉 Environment check completed'));