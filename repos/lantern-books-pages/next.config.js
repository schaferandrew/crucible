/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  // A page that throws while prerendering fails the build in seconds instead of minutes
  staticPageGenerationTimeout: 10,
};
